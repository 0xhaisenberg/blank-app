import tweepy
import re
import datetime
import time
import argparse
from dateutil.relativedelta import relativedelta
from flipside import Flipside
import config


def authenticate_twitter_api():
    """
    Authenticate with the Twitter API v2 using your credentials.
    You need to replace these placeholders with your actual API credentials.
    """
    # For v2 API, you'll need a bearer token
    bearer_token = config.bearer_token
    
    try:
        # Initialize the client with v2 API
        client = tweepy.Client(bearer_token=bearer_token)
        print("Authentication successful!")
        return client
    except Exception as e:
        print(f"Error during authentication: {e}")
        return None

def get_timeframe_date(hours):
    """Calculate the date from which to start gathering tweets based on hours."""
    today = datetime.datetime.now()
    
    # Make sure hours is within range
    if not 1 <= hours <= 24:
        raise ValueError("Time frame must be between 1 and 24 hours")
    
    # Calculate start date based on hours
    start_date = today - datetime.timedelta(hours=hours)
    
    # Format date for Twitter API v2 (ISO 8601 format)
    return start_date.strftime('%Y-%m-%dT%H:%M:%SZ')

def extract_solana_addresses(text):
    """
    Extract Solana addresses from text.
    Solana addresses are typically 32-44 characters long and Base58 encoded.
    """
    if not text:
        return []
        
    # Common Solana address patterns:
    # - Start with a specific pattern (often begins with a number or specific characters)
    # - Are 32-44 characters in length
    # - Consist of alphanumeric characters (Base58 encoding: 1-9, A-H, J-N, P-Z, a-k, m-z)
    solana_pattern = r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b'
    
    # Find all matches
    potential_addresses = re.findall(solana_pattern, text)
    
    # Filter out addresses that don't match Solana's format
    # This is a simplified check - for production, you might want more validation
    valid_addresses = []
    for addr in potential_addresses:
        # Additional validation could be added here
        valid_addresses.append(addr)
    
    return valid_addresses

def get_user_tweets(client, username, timeframe_hours):
    """Get tweets from a specific user within the given time frame using Twitter API v2."""
    start_time = get_timeframe_date(timeframe_hours)
    
    try:
        # First, get the user ID from the username
        user_response = client.get_user(username=username)
        if not user_response.data:
            print(f"User @{username} not found.")
            return []
            
        user_id = user_response.data.id
        
        # Get user tweets
        tweets = []
        
        # API v2 uses pagination token
        pagination_token = None
        
        # We'll make multiple requests if needed to get more tweets
        max_requests = 10  # Set a limit to avoid too many requests
        request_count = 0
        
        while request_count < max_requests:
            request_count += 1
            
            # Make the API request
            response = client.get_users_tweets(
                id=user_id,
                max_results=100,  # Maximum allowed per request
                start_time=start_time,
                tweet_fields=['created_at', 'text'],
                pagination_token=pagination_token
            )
            
            # Check if we got any data
            if not response.data:
                break
                
            tweets.extend(response.data)
            
            # Check if there are more tweets to fetch
            if not response.meta.get('next_token'):
                break
                
            pagination_token = response.meta['next_token']
            
            # Be nice to the API with a short delay
            time.sleep(1)
            
        return tweets
    except Exception as e:
        print(f"Error fetching tweets: {e}")
        return []

def get_user_input():
    """Get username and timeframe from user input."""
    # Get Twitter username
    username = input("Enter the Twitter username (without @): ")
    
    # Get timeframe in hours
    while True:
        try:
            timeframe = int(input("Enter the timeframe in hours (1-24): "))
            if not 1 <= timeframe <= 24:
                print("Invalid timeframe. Please enter a number between 1 and 24.")
                continue
            break
        except ValueError:
            print("Please enter a valid number.")
    
    return username, timeframe

def query_flipside_data(addresses, timestamps):
    """
    Query Flipside data for the given Solana addresses and around the given timestamps.
    
    Args:
        addresses: List of Solana addresses
        timestamps: List of timestamps corresponding to when each address was found
    """
    
    # Initialize Flipside with API Key
    flipside = Flipside(config.api_key, "https://api-v2.flipsidecrypto.xyz")
    
    # Format addresses for SQL query
    addresses_str = "', '".join(addresses)
    
    # For each address, we'll build queries around its timestamp
    all_results = []
    
    for i, (address, timestamp) in enumerate(zip(addresses, timestamps)):
        # Convert the timestamp string to datetime object
        tweet_time = datetime.datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S UTC')
        
        # Define time range: 2 hours before and 24 hours after the tweet
        start_time = tweet_time - datetime.timedelta(hours=2)
        end_time = tweet_time + datetime.timedelta(hours=24)
        
        # Format timestamps for SQL
        start_time_str = start_time.strftime('%Y-%m-%d %H:%M:%S')
        end_time_str = end_time.strftime('%Y-%m-%d %H:%M:%S')
        
        print(f"\nQuerying Flipside for address {i+1}/{len(addresses)}: {address}")
        print(f"Time range: {start_time_str} to {end_time_str}")
        
        sql = f"""
        WITH token_swap_prices AS (
          SELECT
            block_timestamp,
            date_trunc('hour', block_timestamp) AS hour,
            CASE
              WHEN swap_from_mint = 'So11111111111111111111111111111111111111112' THEN swap_to_mint
              WHEN swap_to_mint = 'So11111111111111111111111111111111111111112' THEN swap_from_mint
            END AS token_address,
            CASE
              WHEN swap_from_symbol = 'SOL' THEN swap_to_symbol
              WHEN swap_to_symbol = 'SOL' THEN swap_from_symbol
            END AS token_symbol,
            CASE
              WHEN swap_from_mint = 'So11111111111111111111111111111111111111112' THEN swap_from_amount_usd / NULLIF(swap_to_amount, 0)
              WHEN swap_to_mint = 'So11111111111111111111111111111111111111112' THEN swap_to_amount_usd / NULLIF(swap_from_amount, 0)
            END AS token_price_usd
          FROM
            solana.defi.ez_dex_swaps
          WHERE
            (
              (swap_to_mint IN ('{address}') AND swap_from_mint = 'So11111111111111111111111111111111111111112')
              OR
              (swap_from_mint IN ('{address}') AND swap_to_mint = 'So11111111111111111111111111111111111111112')
            )
            AND (
              (swap_from_mint = 'So11111111111111111111111111111111111111112' AND swap_to_amount > 0)
              OR
              (swap_to_mint = 'So11111111111111111111111111111111111111112' AND swap_from_amount > 0)
            ) -- avoid division by zero
            AND block_timestamp BETWEEN '{start_time_str}' AND '{end_time_str}'
        )
        SELECT
          hour,
          token_address,
          token_symbol,
          AVG(token_price_usd) AS avg_token_price_usd,
          COUNT(*) as swap_count
        FROM
          token_swap_prices
        WHERE
          token_address IS NOT NULL
          AND token_price_usd IS NOT NULL
        GROUP BY
          1, 2, 3
        ORDER BY
          1
        """
        
        # Run the query against Flipside's query engine and await the results
        try:
            query_result_set = flipside.query(sql)
            
            # Check if the query was successful and process results
            if query_result_set and hasattr(query_result_set, 'records') and query_result_set.records:
                print(f"Found {len(query_result_set.records)} swap records for address {address}")
                
                # Store the results along with metadata
                address_result = {
                    'address': address,
                    'tweet_timestamp': timestamp,
                    'data': query_result_set.records
                }
                
                all_results.append(address_result)
                
                # Print a summary of the price data
                print("\nPrice Summary:")
                print(f"{'Timestamp':<25} {'Symbol':<10} {'Price (USD)':<15} {'Swap Count'}")
                print("-" * 65)

                for record in query_result_set.records:
                    hour = record['hour']
                    symbol = record['token_symbol'] or 'Unknown'
                    price = record['avg_token_price_usd']
                    count = record['swap_count']
                    
                    # Handle hour whether it's a datetime object or string
                    hour_str = hour.strftime('%Y-%m-%d %H:%M:%S') if hasattr(hour, 'strftime') else str(hour)
                    
                    print(f"{hour_str:<25} {symbol:<10} ${price:<14.6f} {count}")
                
            else:
                print(f"No swap data found for address {address} in the specified time range.")
        
        except Exception as e:
            print(f"Error querying Flipside for address {address}: {e}")
    
    return all_results

def main():
    # Get user input
    username, timeframe = get_user_input()
    
    # Authenticate with Twitter API v2
    client = authenticate_twitter_api()
    if not client:
        return
    
    # Get tweets
    print(f"Fetching tweets for @{username} within the last {timeframe} hours...")
    tweets = get_user_tweets(client, username, timeframe)
    
    if not tweets:
        print(f"No tweets found for @{username} in the last {timeframe} hours (or API access is limited).")
        return
        
    print(f"Found {len(tweets)} tweets. Scanning for Solana addresses...")
    
    # Process tweets and extract Solana addresses
    # Use a dictionary to store earliest occurrence of each address
    address_dict = {}
    
    # Sort tweets by creation date (oldest first)
    # This ensures we process older tweets first when possible
    sorted_tweets = sorted(tweets, key=lambda x: x.created_at if hasattr(x, 'created_at') else datetime.datetime.max)
    
    for tweet in sorted_tweets:
        addresses = extract_solana_addresses(tweet.text)
        
        for address in addresses:
            # Format the timestamp
            if hasattr(tweet, 'created_at'):
                timestamp = tweet.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')
                tweet_datetime = tweet.created_at
            else:
                timestamp = "Unknown"
                tweet_datetime = datetime.datetime.max
            
            # Store this occurrence if it's the first time we see this address
            # or if it's older than what we already have
            if address not in address_dict or tweet_datetime < address_dict[address]['datetime']:
                address_dict[address] = {
                    'timestamp': timestamp,
                    'datetime': tweet_datetime,
                    'tweet_text': tweet.text
                }
    
    # Convert dictionary to list of results for display
    results = [(addr, data['timestamp'], data['tweet_text']) for addr, data in address_dict.items()]
    
    # Display results
    if results:
        print(f"\nFound {len(results)} unique Solana contract addresses in tweets by @{username}:")
        print("-" * 100)
        print(f"{'Timestamp':<25} {'Solana Contract Address':<45} {'Tweet Text Preview'}")
        print("-" * 100)
        for address, timestamp, tweet_text in results:
            # Truncate tweet text for display
            preview = (tweet_text[:50] + '...') if len(tweet_text) > 50 else tweet_text
            print(f"{timestamp:<25} {address:<45} {preview}")
            
        # Ask if user wants to query Flipside for these addresses
        choice = input("\nDo you want to query Flipside for swap data related to these addresses? (y/n): ")
        
        if choice.lower() == 'y':
            # Extract lists of addresses and timestamps to pass to Flipside query
            addresses = [addr for addr, _, _ in results]
            timestamps = [ts for _, ts, _ in results]
            
            # Query Flipside for each address
            flipside_results = query_flipside_data(addresses, timestamps)
            
            # Additional processing of Flipside results could be added here
            # For example, saving to a file, more detailed analysis, etc.
            
            if flipside_results:
                print("\nAll Flipside queries completed successfully.")
            else:
                print("\nNo Flipside data was found for the specified addresses and time ranges.")
    else:
        print(f"No Solana contract addresses found in tweets by @{username} in the last {timeframe} hours.")

if __name__ == "__main__":
    main()
