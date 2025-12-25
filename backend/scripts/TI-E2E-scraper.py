import asyncio
import aiohttp
import time
import json
import random
from bs4 import BeautifulSoup
import os
from datetime import datetime
from playwright.async_api import async_playwright

########################
# 1) GLOBAL HELPERS
########################

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 12_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36"


async def fetch_page_full(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url)
        content = await page.content()
        await browser.close()
        return content


async def fetch_html(session, url, sem,
                     min_delay=0.1, max_delay=0.3):
    """
    Fetch the raw HTML of 'url' using an aiohttp session,
    respecting concurrency with 'sem', adding a small random delay
    to avoid hammering the server, and using a custom User-Agent.

    If we get a 403, we print a warning about a restricted page
    and return None so we skip parsing.
    """
    async with sem:
        # random short sleep to avoid bursts (helps avoid 403)
        await asyncio.sleep(random.uniform(min_delay, max_delay))

        try:
            async with session.get(url, headers={"User-Agent": USER_AGENT}) as resp:
                if resp.status == 403:
                    # restricted or blocked
                    print(f"*** 403 Forbidden: {url} (Skipping...)")
                    return None
                resp.raise_for_status()  # raise for 4xx/5xx
                return await resp.text()
        except aiohttp.ClientResponseError as e:
            # Could be 404, 500, etc.
            print(f"*** HTTP Error {e.status} on {url} (Skipping...)")
            return None
        except aiohttp.ClientError as e:
            # Generic network issues, timeouts, etc.
            print(f"*** Client Error fetching {url}: {e}")
            return None
        except asyncio.TimeoutError:
            print(f"*** Timeout for {url}")
            return None


async def get_last_page_number(session, url, sem):
    """Fetch the HTML and extract the last page number from the pagination link."""
    html = await fetch_page_full(url)
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")

    last_page_links = soup.find_all(
        "a", class_="last", attrs={"data-type": "last"})

    last_page_link = max(last_page_links, key=lambda x: int(
        x["data-page"])) if last_page_links else None
    if last_page_link:
        # Try data-page first
        if "data-page" in last_page_link.attrs:
            try:
                return int(last_page_link["data-page"])
            except ValueError:
                print(
                    f"Invalid data-page value: {last_page_link['data-page']}")

    return None


def parse_listing_page(html):
    """
    Parse a listing page (forum index) to find:
      - question title
      - question URL
      - answered status
    Returns a list of dicts => [{"title": "...", "url": "...", "status": "..."}]
    """
    if not html:
        return []  # If the fetch returned None (403 or error), skip
    soup = BeautifulSoup(html, "html.parser")
    results = []

    question_divs = soup.select("div.name.cell")
    for div in question_divs:
        link_el = div.select_one("a.internal-link.view-post")
        if not link_el:
            continue

        title = link_el.get_text(strip=True)
        url = link_el.get("href", "")
        status = "Unknown"

        # Status div can be preceding or following
        status_div = (div.find_previous_sibling("div", class_="icon cell answer-status")
                      or div.find_next_sibling("div", class_="icon cell answer-status"))
        if status_div:
            # "Question answered"
            if status_div.select_one("a.ui-tip.verified.replace-with-icon.check[title^='Question answered']"):
                status = "Answered"
            # "Answer suggested"
            elif status_div.select_one("a.ui-tip.suggested.replace-with-icon.check[title^='Answer suggested']"):
                status = "Answered"
            # "Unanswered"
            elif status_div.select_one("span.attribute-value.unanswered.ui-tip.replace-with-icon.help"):
                status = "Not Answered"
            else:
                status = "Unknown"

        results.append({"title": title, "url": url, "status": status})

    return results


def parse_detail_page(html):
    """
    Parse a detail page for question content + verified/suggested answer text.
    Returns {"question": "...", "answer": "..."} or "No" placeholders if missing.
    """
    if not html:
        return {"question": "No Question Found", "answer": "No Answer Found"}

    soup = BeautifulSoup(html, "lxml")

    # question text
    question_div = soup.select_one(
        "div.thread-start div.content.full div.content")
    question_text = question_div.get_text(
        strip=True) if question_div else "No Question Found"

    # answer text
    answer_div = soup.find("div", class_=lambda c: c and (
        "suggested" in c or "verified" in c))
    if answer_div:
        content_div = answer_div.find("div", class_="content")
        answer_text = content_div.get_text(
            strip=True) if content_div else "No Answer Found"
    else:
        answer_text = "No Answer Found"

    return {"question": question_text, "answer": answer_text}

########################
# 2) ASYNC LISTING
########################


async def gather_listing_pages(start_page, end_page, existing_urls, concurrency=5):
    """
    Fetch listing pages from start_page..end_page in parallel
    (with concurrency=5).
    Return a combined list of question dicts.
    """
    base_url_1 = "https://e2e.ti.com/support/processors-group/processors/f/processors-forum"
    base_url_n = "https://e2e.ti.com/support/processors-group/processors/f/processors-forum?pifragment-322293={}"

    sem = asyncio.Semaphore(concurrency)

    async with aiohttp.ClientSession() as session:
        tasks = []
        for page in range(start_page, end_page + 1):
            if page == 1:
                tasks.append(fetch_html(session, base_url_1, sem))
            else:
                url = base_url_n.format(page)
                tasks.append(fetch_html(session, url, sem))

        pages_html = await asyncio.gather(*tasks)

    # debug purpose
    all_listings_len = 0
    # parse
    all_new_listings = []

    for html in pages_html:
        listing_data = parse_listing_page(html)
        # print out how many listings we found

        new_listings = [
            q for q in listing_data if q["url"] not in existing_urls]
        all_new_listings.extend(new_listings)
        all_listings_len += len(listing_data)

    print(
        f"  Found {all_listings_len} listings in pages {start_page} to {end_page}.")
    return all_new_listings

########################
# 3) ASYNC DETAILS
########################


async def gather_detail_pages(answered_questions, concurrency=10):
    """
    For each answered question, fetch & parse the detail page.
    concurrency=10 by default for detail pages.
    """
    sem = asyncio.Semaphore(concurrency)

    async with aiohttp.ClientSession() as session:
        tasks = [fetch_html(session, q["url"], sem)
                 for q in answered_questions]
        detail_htmls = await asyncio.gather(*tasks)

    results = []
    for i, question in enumerate(answered_questions):
        qa = parse_detail_page(detail_htmls[i])
        results.append({
            "title": question["title"],
            "url": question["url"],
            "question": qa["question"],
            "answer": qa["answer"]
        })
    return results

########################
# 4) MAIN CHUNK SCRAPER
########################


async def scrape_ti_e2e_forum_async(output_file, chunk_size=100, previous_files_directory=None, num_pages=None, overwrite_last_page=None):
    """
    Scrape 'num_pages' pages in chunks of size 'chunk_size'.
    Combine all 'answered' detail results into a single JSON.
    """
    start_time = time.time()

    existing_urls = set()

    if previous_files_directory and os.path.isdir(previous_files_directory):
        for filename in os.listdir(previous_files_directory):
            if filename.endswith(".json"):
                file_path = os.path.join(previous_files_directory, filename)
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    existing_urls.update(item["url"] for item in data)
        print(
            f"Loaded {len(existing_urls)} existing URLs from files in '{previous_files_directory}'.")
    else:
        print("No previous files directory provided or found. Scraping all data as new.")

    base_url = "https://e2e.ti.com/support/processors-group/processors/f/processors-forum"
    sem = asyncio.Semaphore(5)
    async with aiohttp.ClientSession() as session:
        last_page = overwrite_last_page if overwrite_last_page is not None else await get_last_page_number(session, base_url, sem)
        if num_pages is not None:
            print(f"Using provided num_pages: {num_pages}")
        elif last_page:
            num_pages = last_page
            print(f"Detected last page: {last_page}, using it as num_pages.")
        else:
            print(
                "No num_pages provided and could not determine last page. Defaulting to 1.")
            num_pages = 1

    all_results = []

    # For each chunk
    for chunk_start in range(1, num_pages+1, chunk_size):
        chunk_end = min(num_pages, chunk_start + chunk_size - 1)
        print(f"\n=== Processing pages {chunk_start} to {chunk_end} ===")

        # PASS 1: listing
        listings = await gather_listing_pages(chunk_start, chunk_end, existing_urls, concurrency=5)
        print(
            f"  Found {len(listings)} total NEW questions in pages {chunk_start}-{chunk_end}.")

        answered = [q for q in listings if q["status"] == "Answered"]
        print(f"  {len(answered)} ANSWERED questions found. Fetching details...")

        # PASS 2: detail
        details = await gather_detail_pages(answered, concurrency=10)
        print(
            f"  Retrieved {len(details)} detail pages for chunk {chunk_start}-{chunk_end}.")

        all_results.extend(details)

    # after all chunks
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=4, ensure_ascii=False)

    elapsed = time.time() - start_time
    print(
        f"\nAll chunks complete! Wrote {len(all_results)} items to '{output_file}'.")
    print(f"Total run time: {elapsed:.2f} seconds.")


def scrape_ti_e2e_forum(output_file="answered_ti_e2e.json", chunk_size=100, previous_files_directory="data/", overwrite_last_page=None):
    """
    Launcher: calls the async code with asyncio.run().
    By default, scrapes 9600 pages in chunks of 100 pages each.
    """
    asyncio.run(scrape_ti_e2e_forum_async(output_file, chunk_size, previous_files_directory, overwrite_last_page))


import argparse
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--overwriteLastPage", type=int, help="Override last page number")
    args = parser.parse_args()
    # Example: parse 9600 pages in chunks of 100
    current_date = datetime.now().strftime("%Y-%m-%d")

    data_dir = "/datasets/"
    output_filename = f"{data_dir}answered_ti_e2e_{current_date}.json"

    # Delete the file if it already exists
    if os.path.exists(output_filename):
        os.remove(output_filename)
        print(f"File {output_filename} already exists. Rerunning the scraper...")

    print("Starting the scraper...")
    scrape_ti_e2e_forum(output_file=output_filename, chunk_size=100, previous_files_directory=data_dir, overwrite_last_page=args.overwriteLastPage)