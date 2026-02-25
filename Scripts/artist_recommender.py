import pandas as pd
import numpy as np
import re

def get_recommendations(df):
    """
    Python implementation of the R fuzzy recommender logic.
    Identifies missing artists based on library similarity and play counts.
    """
    # 1. Clean Library Artists for matching
    def clean_key(text):
        if not isinstance(text, str): return ""
        # Lowercase, remove punctuation, trim
        return re.sub(r'[^\w\s]', '', text.lower()).strip()

    # Ensure Artist_Genres is in the dataframe to avoid KeyErrors
    if 'Artist_Genres' not in df.columns:
        df['Artist_Genres'] = ""

    # Create Artist-Level dataframe and ensure numeric types
    artist_df = df[['Artist', 'Similar_Artists', 'Total_Plays', 'Artist_Genres']].drop_duplicates('Artist').copy()
    
    # FIX: Convert Total_Plays from string to numeric, turning errors into 0
    artist_df['Total_Plays'] = pd.to_numeric(artist_df['Total_Plays'], errors='coerce').fillna(0)
    artist_df['Artist_Genres'] = artist_df['Artist_Genres'].fillna("")
    
    artist_df = artist_df[artist_df['Artist'].notna()]

    # Create canonical list of library keys
    library_clean = set(artist_df['Artist'].apply(clean_key).unique())

    # 2. Expand Similar Artists rows
    recs = artist_df.assign(Similar_Artists=artist_df['Similar_Artists'].str.split(r',\s*')).explode('Similar_Artists')
    recs = recs[recs['Similar_Artists'].notna() & (recs['Similar_Artists'] != "")]

    # Create match keys for suggested artists
    recs['suggested_key'] = recs['Similar_Artists'].apply(clean_key)

    # THE FUZZY FILTER: Only keep if the artist is NOT in your library
    recs = recs[~recs['suggested_key'].isin(library_clean)]

    # Helper function to extract, deduplicate, and alphabetically sort genres
    def get_unique_genres(genre_series):
        genres = set()
        for g_str in genre_series:
            if isinstance(g_str, str) and g_str.strip():
                # Split by comma and strip whitespace
                genres.update([g.strip() for g in g_str.split(',') if g.strip()])
        # Sort alphabetically (case-insensitive) and join
        return ", ".join(sorted(genres, key=lambda x: x.lower()))

    # 3. Summarize and Score
    recommendations = recs.groupby('Similar_Artists').agg(
        Related_Library_Artists=('Artist', lambda x: ", ".join(x.unique())),
        Recommendation_Count=('Artist', 'count'),
        Related_Library_Artists_Total_Play_Count=('Total_Plays', 'sum'),
        Related_Artist_Genres=('Artist_Genres', get_unique_genres)
    ).reset_index()

    # Calculate Hybrid Score: Count * log10(Total Plays + 1)
    recommendations['Priority_Score'] = (
        recommendations['Recommendation_Count'] * np.log10(recommendations['Related_Library_Artists_Total_Play_Count'] + 1)
    )

    # Rename the missing artist column
    recommendations = recommendations.rename(columns={'Similar_Artists': 'Missing_Artist'})
    
    # Reorder columns to ensure Related_Artist_Genres is last
    col_order = [
        'Missing_Artist', 
        'Related_Library_Artists', 
        'Recommendation_Count', 
        'Related_Library_Artists_Total_Play_Count', 
        'Priority_Score', 
        'Related_Artist_Genres'
    ]
    
    return recommendations[col_order].sort_values('Priority_Score', ascending=False)