import pandas as pd
import numpy as np
import re
import os
from datetime import timedelta

# Load CSV
df = pd.read_csv(r"C:\Users\aspir\OneDrive - Westmont College\Documents\NBA_Injury_Scraper\data\injuries_2015-2025.csv")

# Step 1: Strip whitespace
df = df.applymap(lambda x: x.strip() if isinstance(x, str) else x)

# Step 2: Convert 'Date'
df['Date'] = pd.to_datetime(df['Date'], errors='coerce')

# Step 3: Clean corrupted characters
weird_chars = ['•', 'â€¢', 'Ã', 'Â', '“', '”']
for col in ['Acquired', 'Relinquished', 'Notes']:
    for char in weird_chars:
        df[col] = df[col].str.replace(char, '', regex=False)
    df[col] = df[col].str.replace(r'\s+', ' ', regex=True).str.strip()

# Step 4: Create 'Player' column
def choose_player(row):
    if pd.notna(row['Acquired']) and row['Acquired'] != '':
        return row['Acquired']
    elif pd.notna(row['Relinquished']) and row['Relinquished'] != '':
        return row['Relinquished']
    return np.nan

df['Player'] = df.apply(choose_player, axis=1)

# Normalize 'Team'
df['Team'] = df['Team'].str.strip().str.title()

# Step 5: Add basic date fields
df['Year'] = df['Date'].dt.year
df['Month'] = df['Date'].dt.month
df['YearMonth'] = df['Date'].dt.to_period('M').astype(str)

# Step 6: Sort
df.sort_values(by=['Player', 'Date'], inplace=True)

# Step 7: Duration category from Notes
def categorize_duration(note):
    if pd.isna(note):
        return np.nan
    note = note.lower()
    if 'out for season' in note or 'season-ending' in note:
        return 'out for season'
    elif 'out indefinitely' in note:
        return 'indefinitely'
    elif 'day-to-day' in note or 'dtd' in note or 'rest' in note:
        return 'day-to-day'
    elif 'returned to lineup' in note:
        return 'returned'
    elif 'surgery' in note:
        return 'post-surgery'
    elif 'concussion' in note:
        return 'concussion protocol'
    else:
        return 'other / unspecified'

df['DurationCategory'] = df['Notes'].apply(categorize_duration)

# Step 8: Extract injury keyword
def extract_injury_keyword(note):
    keywords = [
        'ankle', 'knee', 'back', 'wrist', 'shoulder', 'hamstring', 'calf',
        'concussion', 'acl', 'achilles', 'illness', 'foot', 'surgery',
        'hand', 'finger', 'toe', 'leg', 'rest', 'quad', 'groin', 'rib',
        'nose', 'thigh', 'hip'
    ]
    if pd.isna(note):
        return None

    # Normalize encoding, lowercase, remove punctuation, normalize whitespace
    note = str(note)
    note_clean = (
        note.encode("ascii", "ignore").decode("ascii").lower()
    )
    note_clean = re.sub(r"[^\w\s]", " ", note_clean)  # remove punctuation
    note_clean = re.sub(r"\s+", " ", note_clean).strip()

    for kw in keywords:
        if kw in note_clean:
            return kw
    return 'Other'

# Apply the fix
df['InjuryKeyword'] = df['Notes'].apply(extract_injury_keyword)

# Define default season-end date based on the year of injury
def get_season_end(injury_date):
    if pd.isna(injury_date):
        return np.nan
    year = injury_date.year if injury_date.month >= 10 else injury_date.year - 1
    return pd.Timestamp(f"{year + 1}-06-15")

# Step 10: Compute Actual and In-Season Duration
def count_in_season_days(start, end):
    if pd.isna(start) or pd.isna(end):
        return np.nan
    days = pd.date_range(start, end)
    count = 0
    for day in days:
        if (day.month >= 10 or day.month <= 6):  # Oct–Jun
            if (day.month == 6 and day.day > 15) or (day.month == 9 and day.day < 30):
                continue
            count += 1
    return count

# Build injury records
injury_records = []

for (player, team), group in df.groupby(['Player', 'Team']):
    injury_start = None
    returned = False
    for _, row in group.iterrows():
        if pd.isna(row['Acquired']) and pd.notna(row['Relinquished']):
            injury_start = row['Date']
            returned = False
        elif pd.notna(row['Acquired']) and pd.isna(row['Relinquished']):
            if injury_start and row['Date'] >= injury_start:
                full_days = (row['Date'] - injury_start).days
                in_season_days = count_in_season_days(injury_start, row['Date'])
                injury_records.append({
                    'Player': player,
                    'Team': team,
                    'Injury_Start': injury_start,
                    'Injury_End': row['Date'],
                    'Actual_Duration_Days': full_days,
                    'InSeason_Duration_Days': in_season_days,
                    'Return_Notes': row['Notes']
                })
                injury_start = None
                returned = True
    # If player never returned, assign June 15 as end
    if injury_start and not returned:
        season_end = get_season_end(injury_start)
        full_days = (season_end - injury_start).days
        in_season_days = count_in_season_days(injury_start, season_end)
        injury_records.append({
            'Player': player,
            'Team': team,
            'Injury_Start': injury_start,
            'Injury_End': season_end,
            'Actual_Duration_Days': full_days,
            'InSeason_Duration_Days': in_season_days,
            'Return_Notes': 'No return transaction – assumed out for season'
        })

injury_df = pd.DataFrame(injury_records)

# Step 9: Estimate days out from Notes
duration_estimates = {
    'day-to-day': 3,
    'indefinitely': 30,
    'out for season': 180,
    'returned': 0,
    'post-surgery': 60,
    'concussion protocol': 7,
    'other / unspecified': np.nan
}

df['DurationCategory'] = df['DurationCategory'].astype(str).str.strip().str.lower()
df['EstimatedDaysOutFromNotes'] = df['DurationCategory'].map(duration_estimates)

# Step 10: Flag full-season injuries
injury_df['OutForSeason'] = injury_df['Return_Notes'].str.contains('assumed out for season', case=False, na=False)


# Step 11: Merge durations into main DataFrame
df = pd.merge(
    df,
    injury_df[['Player', 'Team', 'Injury_Start', 'Injury_End', 'Actual_Duration_Days', 'InSeason_Duration_Days']],
    on=['Player', 'Team'],
    how='left'
)

# Step 12: Remove return rows
df = df[df['Acquired'].isna()].copy()

# Step 13: Drop 'Acquired'
df.drop(columns=['Acquired'], inplace=True)

# Step 14: Remove duplicates
df = df.drop_duplicates(subset=['Player', 'Team', 'Date', 'Notes'])

# Step 15: Final date columns
df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
df['Month'] = df['Date'].dt.month_name()
df['DayOfWeek'] = df['Date'].dt.day_name()

# Step 16: Save file
output_path = "injuries_2015-2025-cleanednew.csv"
df.to_csv(output_path, index=False, encoding='utf-8-sig')
print(f"✅ Cleaned file saved to: {output_path}")

!pip install ydata-profiling

from ydata_profiling import ProfileReport

profile = ProfileReport(df, title="NBA Injury Data Profiling Report", explorative=True)
profile.to_file("nba_injury_profile.html")

