import os
import csv
import time
import random
import requests
import re
from bs4 import BeautifulSoup
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 配置参数 ---
BASE_URL = "https://oilprice.com/Latest-Energy-News/World-News/"
PAGE_LIMIT = 1271
MAX_THREADS = 20  # 建议不要设置太高，以防被封

# 目录结构
ROOT_DIR = "OilPrice_Project"
TEXT_DIR = os.path.join(ROOT_DIR, "Articles_FullText")
SUMMARY_CSV = os.path.join(ROOT_DIR, "news_summary.csv")
ERROR_CSV = os.path.join(ROOT_DIR, "error_log.csv")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Referer": "https://oilprice.com/"
}

# --- 工具函数 ---

def init_folders():
    """初始化文件夹和CSV文件"""
    if not os.path.exists(TEXT_DIR):
        os.makedirs(TEXT_DIR)
    
    if not os.path.exists(SUMMARY_CSV):
        with open(SUMMARY_CSV, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(["发布时间", "新闻标题", "新闻页面链接"])
            
    if not os.path.exists(ERROR_CSV):
        with open(ERROR_CSV, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(["类型", "URL", "错误原因", "处理时间"])

def get_done_urls():
    """获取已成功爬取的URL列表"""
    done_urls = set()
    if os.path.exists(SUMMARY_CSV):
        with open(SUMMARY_CSV, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                done_urls.add(row["新闻页面链接"])
    return done_urls

def parse_iso_time(time_str):
    """
    将 'Feb 10, 2026, 12:30 PM CST' 转换为 ISO 格式
    """
    try:
        # 去掉时区简写 (如 CST, EST)，strptime 对非标准时区支持有限
        clean_time = re.sub(r'\s[A-Z]{3,4}$', '', time_str.strip())
        dt = datetime.strptime(clean_time, "%b %d, %Y, %I:%M %p")
        return dt.isoformat()
    except:
        return datetime.now().strftime("%Y-%m-%dT%H-%M-%S")

def log_failure(err_type, url, reason):
    """记录失败信息"""
    with open(ERROR_CSV, 'a', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow([err_type, url, reason, datetime.now().isoformat()])

# --- 核心逻辑 ---

def crawl_article(url, list_title):
    """抓取详情页内容并保存"""
    try:
        # time.sleep(random.uniform(1.2, 2.5))
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            log_failure("内容页访问失败", url, f"Status: {resp.status_code}")
            return False

        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # 1. 提取精确时间 (位于 class="article_byline")
        byline = soup.find('span', class_='article_byline')
        if byline:
            # 提取日期时间字符串
            raw_time_text = byline.get_text().split('-')[-1].strip()
            iso_time = parse_iso_time(raw_time_text)
        else:
            iso_time = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")

        # 2. 提取正文内容
        content_div = soup.find('div', id='news-content')
        if not content_div:
            content_div = soup.find('article')
            
        if not content_div:
            log_failure("正文解析失败", url, "找不到 id=news-content")
            return False

        # 获取所有段落文本
        paragraphs = content_div.find_all('p')
        article_text = "\n\n".join([p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)])
        
        if not article_text:
            log_failure("正文为空", url, "标签存在但无文字")
            return False

        # 3. 保存 TXT
        # 文件名不能包含 : ，将 ISO 时间中的 : 替换为 -
        file_time = iso_time.replace(':', '-')
        safe_title = re.sub(r'[\\/:*?"<>|]', '', list_title).strip()
        file_name = f"{file_time}_{safe_title}.txt"
        
        with open(os.path.join(TEXT_DIR, file_name), 'w', encoding='utf-8') as f:
            f.write(f"ISO_TIME: {iso_time}\n")
            f.write(f"TITLE: {list_title}\n")
            f.write(f"LINK: {url}\n")
            f.write("-" * 30 + "\n\n")
            f.write(article_text)

        # 4. 写入 CSV
        with open(SUMMARY_CSV, 'a', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow([iso_time, list_title, url])
        
        return True

    except Exception as e:
        log_failure("系统异常", url, str(e))
        return False

def get_list_page(page_num):
    """解析目录页"""
    url = BASE_URL if page_num == 1 else f"{BASE_URL}Page-{page_num}.html"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            return []
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        articles = soup.find_all('div', class_='categoryArticle')
        
        found = []
        for art in articles:
            link_tag = art.find('a', href=True)
            title_tag = art.find('h2')
            if link_tag and title_tag:
                found.append({
                    'link': link_tag['href'],
                    'title': title_tag.get_text(strip=True)
                })
        return found
    except:
        return []

# --- 执行入口 ---

def main():
    init_folders()
    processed_urls = get_done_urls()
    print(f"任务启动。已跳过 {len(processed_urls)} 篇已下载文章。")

    for page in range(1, PAGE_LIMIT + 1):
        print(f"\n正在扫描目录第 {page} 页...")
        entries = get_list_page(page)
        
        # 过滤
        todo = [e for e in entries if e['link'] not in processed_urls]
        
        if not todo:
            continue

        # 多线程爬取详情
        with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
            future_to_url = {executor.submit(crawl_article, item['link'], item['title']): item['link'] for item in todo}
            
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    if future.result():
                        print(f"成功保存: {url[:60]}...")
                    else:
                        print(f"提取失败: {url}")
                except Exception as e:
                    print(f"意外崩溃: {url} -> {e}")

        # 页间休息
        # time.sleep(random.uniform(1.2, 2.5))

if __name__ == "__main__":
    main()