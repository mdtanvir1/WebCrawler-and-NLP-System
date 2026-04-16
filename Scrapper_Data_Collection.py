#!/usr/bin/env python
# coding: utf-8

# In[ ]:


from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup
from csv import writer
import requests
import csv
import pandas as pd
import time
import warnings
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

warnings.filterwarnings('ignore')


# #### Headless Chrome-driver Setup for selenium
#     Configured Selenium to run Chrome in headless mode (no visible browser).
#     Improves efficiency, reduces resource usage, and allows background execution.
#     Necessary because ABC News search pages are dynamically rendered and require a browser.
#     Additional options ensure stability and consistent page loading.

# In[2]:


chrome_options = Options()

# Headless mode
chrome_options.add_argument("--headless=new")

# Stability / speed
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--window-size=1920,1080")
chrome_options.add_argument("--user-agent=Mozilla/5.0")
chrome_options.page_load_strategy = "eager"

s = Service(r'E:\Data Science\MSc In Data Science\Data science masterclass\chromedriver.exe')
driver = webdriver.Chrome(service=s, options=chrome_options)


# #### Search URL Generation
# 
#     Constructed search URLs using combinations of:
#         cost-of-living-related keywords
#         Australian cities and states
#     Ensures broad and diverse coverage of the topic.
#     Captures regional variations in how the cost-of-living crisis is reported.
#     Query encoding ensures URLs are correctly formatted for the website.

# In[3]:


import urllib.parse

base_topics = [
    "cost of living",
    "housing affordability",
    "rent increase",
    "grocery prices",
    "energy bills",
    "inflation"
]

locations = [
    "Brisbane", "Queensland",
    "Sydney", "New South Wales",
    "Melbourne", "Victoria",
    "Perth", "Western Australia",
    "Adelaide", "South Australia",
    "Hobart", "Tasmania"
]

search_urls = []

for topic in base_topics:
    for loc in locations:
        query = f'"{topic}" "{loc}"'
        encoded_query = urllib.parse.quote(query)
        url = f"https://www.abc.net.au/news/search?query={encoded_query}"
        search_urls.append(url)

print(f"Total search links generated: {len(search_urls)}")
print("Sample URL to visit:", search_urls[0])


# #### Article Link Collection
#     Used Selenium to navigate search result pages and extract article URLs.
#     Implemented pagination to access multiple pages per search query.
#     Stored links in a set to automatically remove duplicates.
#     Focused on collecting links first before scraping content for efficiency.
#     Closed the browser after this step to free system resources.

# In[4]:


all_article_links = set()
wait = WebDriverWait(driver, 6)

for search_url in search_urls:
    driver.get(search_url)

    wait.until(EC.presence_of_element_located((By.XPATH, '//h3/a')))

    for page_num in range(1, 6):
        wait.until(EC.presence_of_all_elements_located((By.XPATH, '//h3/a')))

        title_elements = driver.find_elements(By.XPATH, '//h3/a')

        for element in title_elements:
            href = element.get_attribute('href')
            if href and '/news/' in href:
                all_article_links.add(href)

        # go to next page only if there is another page to visit
        if page_num < 5:
            try:
                next_button = wait.until(
                    EC.element_to_be_clickable((
                        By.XPATH,
                        f"//button[@data-component='Pagination__Page' and text()='{page_num + 1}']"
                    ))
                )

                driver.execute_script("arguments[0].click();", next_button)
                time.sleep(1)

            except:
                break

all_article_links = list(all_article_links)

print(f"Final: {len(all_article_links)} unique article links collected.")

driver.quit()


# #### Article Scraping and Parallel Processing
#     Used requests + BeautifulSoup to extract:
#         title
#         publication date
#         topics
#         article content
#     Implemented parallel scraping (ThreadPoolExecutor) to speed up processing.
#     Significantly reduces runtime compared to sequential scraping.
#     Included fallback extraction logic to handle different webpage structures.

# #### Text Cleaning and Metadata Handling (initial):
#     Make the etracted as clean as possible while extraction
#     Removed non-content elements such as:
#         topic labels (Topic:)
#         author/analysis lines
#         short or irrelevant fragments
#     Extracted topics into a separate column.
#     Cleaned text by:
#         removing duplicates
#         standardising spacing
#         eliminating formatting inconsistencies
#     Improves data quality for NLP tasks (sentiment, topic modelling)

# In[5]:


headers = {
    "User-Agent": "Mozilla/5.0"
}

def is_metadata_line(text):
    text = text.strip()

    if not text:
        return True

    if re.match(r"^Topic\s*:", text, flags=re.I):
        return True

    if re.match(r"^(Analysis|By)\s+", text, flags=re.I):
        return True

    if len(text) < 15:
        return True

    return False

def extract_topics_from_lines(lines):
    topics = []
    for line in lines:
        m = re.match(r"^Topic\s*:\s*(.+)$", line.strip(), flags=re.I)
        if m:
            topic = m.group(1).strip(" .,:;")
            if topic:
                topics.append(topic)
    return topics

def scrape_article(url):
    try:
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.text, "html.parser")

        # Title
        title_tag = soup.find("h1")
        title = title_tag.get_text(strip=True) if title_tag else None

        # Date
        date_tag = soup.find("time")
        date = date_tag.get_text(strip=True) if date_tag else None

        # Extract raw paragraph lines
        raw_lines = []

        article_body = soup.find("article")
        if article_body:
            raw_lines.extend(
                [p.get_text(" ", strip=True) for p in article_body.find_all("p")]
            )

        if len(raw_lines) < 5:
            for section in soup.find_all("div", {"data-component": True}):
                raw_lines.extend(
                    [p.get_text(" ", strip=True) for p in section.find_all("p")]
                )

        if len(raw_lines) < 5:
            raw_lines.extend(
                [p.get_text(" ", strip=True) for p in soup.find_all("p")]
            )

        # Remove blanks and duplicates while preserving order
        seen = set()
        lines = []
        for line in raw_lines:
            line = re.sub(r"\s+", " ", line).strip()
            if line and line not in seen:
                lines.append(line)
                seen.add(line)

        # Extract topics
        topics = extract_topics_from_lines(lines)
        topics_str = ", ".join(topics) if topics else ""

        # Keep only real content lines
        content_lines = [line for line in lines if not is_metadata_line(line)]

        content = " ".join(content_lines)
        content = re.sub(r"\s+", " ", content).strip()

        # Final cleanup
        content = re.sub(r"\bTopic\s*:\s*[^.?!]+", "", content, flags=re.I)
        content = re.sub(r"\bAnalysis by\s+[A-Z][A-Za-z.\- ]+", "", content, flags=re.I)
        content = re.sub(r"\s+([,.:;!?])", r"\1", content)
        content = re.sub(r"\(\s+", "(", content)
        content = re.sub(r"\s+\)", ")", content)
        content = content.strip(" -:;,")

        if not content or len(content) < 100:
            return None

        return {
            "url": url,
            "title": title,
            "date": date,
            "topics": topics_str,
            "content": content
        }

    except:
        return None

articles_data = []

with ThreadPoolExecutor(max_workers=10) as executor:
    futures = [executor.submit(scrape_article, url) for url in all_article_links]

    for future in as_completed(futures):
        result = future.result()
        if result:
            articles_data.append(result)

df = pd.DataFrame(articles_data)

print(f"Scraped {len(df)} clean articles")
df.head()


# In[6]:


df["content"] = (
    df["content"]
    .fillna("")
    .astype(str)
    .str.replace(r"[\t\r\n]+", " ", regex=True)
    .str.replace(r"\s+", " ", regex=True)
    .str.strip()
)


# In[8]:


import csv

for col in ["title", "date", "topics", "content"]:
    df[col] = (
        df[col]
        .fillna("")
        .astype(str)
        .str.replace(r"[\t\r\n]+", " ", regex=True)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )

df.to_csv(
    "abc_articles.csv",
    index=False,
    encoding="utf-8-sig",
    quoting=csv.QUOTE_ALL
)

print("CSV file saved successfully!")

