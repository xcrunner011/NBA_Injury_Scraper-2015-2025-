import time
import pandas as pd
import numpy as np
import re
import os
from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

def replace_all(text, dic):
    rc = re.compile('|'.join(map(re.escape, dic)))
    return rc.sub(lambda match: dic[match.group(0)], text)

char_replace = {' • ': ''}

# Launch undetected Chrome browser
options = uc.ChromeOptions()
options.add_argument("--disable-gpu")
options.add_argument("--window-size=1920,1080")
options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36")
# options.headless = True  # Uncomment this once it's stable

driver = uc.Chrome(options=options)

list_of_rows = []
start = 0
step = 25

while True:
    url = (
        "https://www.prosportstransactions.com/basketball/Search/SearchResults.php"
        "?Player=&Team=&BeginDate=2015-10-27&EndDate=2025-07-31"
        "&ILChkBx=yes&InjuriesChkBx=yes&Submit=Search&start={}".format(start)
    )

    print(f"\n🌐 Loading: {url}")
    driver.get(url)

    try:
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table.datatable.center"))
        )
    except TimeoutException:
        print(f"⏰ Timeout at offset {start}. Retrying once after 5s...")
        time.sleep(5)
        soup = BeautifulSoup(driver.page_source, 'lxml')
        table = soup.find('table')
        if table is None:
            print(f"❌ Still no table at offset {start}. Stopping.")
            break
    else:
        soup = BeautifulSoup(driver.page_source, 'lxml')
        table = soup.find('table')

    if table is None:
        print(f"❌ No table found at offset {start}. Stopping.")
        break

    rows = table.find_all('tr', attrs={'align': 'left'})
    if not rows:
        print(f"✅ No more data at offset {start}. Done scraping.")
        break

    for row in rows:
        cells = row.find_all('td')
        row_data = [replace_all(cell.text.strip(), char_replace) for cell in cells]
        if row_data and len(row_data) == 5:
            list_of_rows.append(row_data)

    print(f"✅ Scraped rows {start} to {start + step}")
    start += step

# Clean shutdown
try:
    driver.quit()
except Exception as e:
    print(f"⚠️ Chrome cleanup warning (can ignore): {e}")

# Save to DataFrame
injuries_df = pd.DataFrame(list_of_rows, columns=[
    'Date', 'Team', 'Acquired', 'Relinquished', 'Notes'
])

# Clean Acquired/Relinquished columns
for col in ['Acquired', 'Relinquished']:
    injuries_df[col] = injuries_df[col].str.replace(r"[\(\[].*?[\)\]]", "", regex=True)
    injuries_df[col] = np.where(
        injuries_df[col].str.contains('/'),
        injuries_df[col].str.split('/ ').str[-1],
        injuries_df[col]
    )

# Create unified Player column
injuries_df['Player'] = injuries_df['Acquired']
injuries_df['Player'] = np.where(
    injuries_df['Player'].isnull() | (injuries_df['Player'] == ''),
    injuries_df['Relinquished'],
    injuries_df['Player']
)

# Reorder columns
injuries_df = injuries_df[['Date', 'Team', 'Player', 'Acquired', 'Relinquished', 'Notes']]

# Parse 'Date' column to datetime
injuries_df['Date'] = pd.to_datetime(injuries_df['Date'], errors='coerce')

# Sort for chronological processing
injuries_df.sort_values(by=['Player', 'Date'], inplace=True)

# Initialize column
injuries_df['EstimatedDaysOut'] = np.nan

# Identify potential injury stints (basic logic)
from collections import defaultdict

last_relinquished_date = defaultdict(lambda: None)

for i, row in injuries_df.iterrows():
    player = row['Player']
    if pd.notna(row['Relinquished']) and player == row['Relinquished']:
        last_relinquished_date[player] = row['Date']
    elif pd.notna(row['Acquired']) and player == row['Acquired']:
        if last_relinquished_date[player] is not None:
            injuries_df.at[i, 'EstimatedDaysOut'] = (row['Date'] - last_relinquished_date[player]).days
            last_relinquished_date[player] = None  # Reset after return


# Save CSV
os.makedirs("data", exist_ok=True)
injuries_df.to_csv("data/injuries_2015-2025.csv", index=False)
print("\n✅ File saved to: data/injuries_2015-2025.csv")
