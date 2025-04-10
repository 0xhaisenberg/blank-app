import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import datetime
import time
from PIL import Image
import base64
import os

# Import functions from main code file
from extractor import (
    authenticate_twitter_api,
    get_user_tweets,
    extract_solana_addresses,
    query_flipside_data
)

# Set page configuration
st.set_page_config(
    page_title="Solana Twitter Tracker",
    page_icon="🌐",
    layout="wide"
)

# Create app header
st.title("🌐 Solana Twitter Tracker")
st.markdown("### Track Solana tokens mentioned on Twitter and analyze their price movements")

# Create sidebar for app controls
st.sidebar.header("Settings")

# User inputs from sidebar
username = st.sidebar.text_input("Twitter Username (without @)", value="")
timeframe = st.sidebar.slider("Timeframe (hours)", min_value=1, max_value=24, value=6)

# Process button
if st.sidebar.button("Analyze Tweets"):
    if not username:
        st.sidebar.error("Please enter a Twitter username")
    else:
        # Show loading spinner
        with st.spinner(f"Analyzing tweets from @{username}..."):
            # Authenticate with Twitter API
            client = authenticate_twitter_api()
            
            if not client:
                st.error("Failed to authenticate with Twitter API. Check your credentials.")
            else:
                # Get tweets
                progress_text = st.empty()
                progress_text.text(f"Fetching tweets for @{username} within the last {timeframe} hours...")
                tweets = get_user_tweets(client, username, timeframe)
                
                if not tweets:
                    st.warning(f"No tweets found for @{username} in the last {timeframe} hours (or API access is limited).")
                else:
                    progress_text.text(f"Found {len(tweets)} tweets. Scanning for Solana addresses...")
                    
                    # Process tweets and extract Solana addresses
                    address_dict = {}
                    
                    # Sort tweets by creation date (oldest first)
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
                        progress_text.text(f"Found {len(results)} unique Solana contract addresses in tweets by @{username}")
                        
                        # Create a dataframe for display
                        df_addresses = pd.DataFrame(results, columns=["Address", "Timestamp", "Tweet Text"])
                        
                        # Display the dataframe
                        st.subheader("Solana Addresses Found")
                        st.dataframe(df_addresses, use_container_width=True)
                        
                        # Extract lists of addresses and timestamps to pass to Flipside query
                        addresses = [addr for addr, _, _ in results]
                        timestamps = [ts for _, ts, _ in results]
                        
                        # Query Flipside for each address
                        progress_text.text("Querying Flipside for price data...")
                        flipside_results = query_flipside_data(addresses, timestamps)
                        progress_text.empty()  # Clear the progress text
                        
                        if flipside_results:
                            st.subheader("Price Analysis")
                            
                            # Create tabs for each address
                            tabs = st.tabs([f"Address {i+1}: {res['address'][:8]}..." for i, res in enumerate(flipside_results)])
                            
                            for i, (tab, result) in enumerate(zip(tabs, flipside_results)):
                                with tab:
                                    address = result['address']
                                    tweet_time = result['tweet_timestamp']
                                    data = result['data']
                                    
                                    if data:
                                        # Convert to DataFrame for easier manipulation
                                        df = pd.DataFrame(data)
                                        
                                        # Convert hour to datetime if it's not already
                                        if not pd.api.types.is_datetime64_any_dtype(df['hour']):
                                            df['hour'] = pd.to_datetime(df['hour'])
                                        
                                        # Display metadata
                                        col1, col2 = st.columns(2)
                                        col1.markdown(f"**Address:** `{address}`")
                                        col1.markdown(f"**Symbol:** {df['token_symbol'].iloc[0] if not df['token_symbol'].iloc[0] is None else 'Unknown'}")
                                        col2.markdown(f"**Tweet Time:** {tweet_time}")
                                        
                                        # Find the tweet time as datetime for plotting the vertical line
                                        tweet_dt = pd.to_datetime(tweet_time.replace(' UTC', ''), utc=True)
                                        
                                        # Create price chart
                                        st.markdown("#### Price Movement")
                                        fig = px.line(
                                            df, 
                                            x='hour', 
                                            y='avg_token_price_usd',
                                            title=f"Price Movement for {df['token_symbol'].iloc[0] if not df['token_symbol'].iloc[0] is None else address[:10]+'...'}"
                                        )
                                        
                                        # Add vertical line for tweet time
                                        fig.add_vline(
                                            x=tweet_dt, 
                                            line_dash="dash", 
                                            line_color="red",
                                            annotation_text="Tweet Time", 
                                            annotation_position="top right"
                                        )
                                        
                                        # Improve layout
                                        fig.update_layout(
                                            xaxis_title="Time",
                                            yaxis_title="Price (USD)",
                                            hovermode="x unified"
                                        )
                                        
                                        st.plotly_chart(fig, use_container_width=True)
                                        
                                        # Create trading volume/swap count chart
                                        st.markdown("#### Trading Activity")
                                        fig2 = px.bar(
                                            df,
                                            x='hour',
                                            y='swap_count',
                                            title=f"Swap Count for {df['token_symbol'].iloc[0] if not df['token_symbol'].iloc[0] is None else address[:10]+'...'}"
                                        )
                                        
                                        # Add vertical line for tweet time
                                        fig2.add_vline(
                                            x=tweet_dt, 
                                            line_dash="dash", 
                                            line_color="red",
                                            annotation_text="Tweet Time", 
                                            annotation_position="top right"
                                        )
                                        
                                        # Improve layout
                                        fig2.update_layout(
                                            xaxis_title="Time",
                                            yaxis_title="Number of Swaps",
                                            hovermode="x unified"
                                        )
                                        
                                        st.plotly_chart(fig2, use_container_width=True)
                                        
                                        # Calculate price change metrics
                                        # Get the first price after tweet time
                                        # Ensuring both are in the same timezone and format:

                                        df['hour'] = pd.to_datetime(df['hour'], utc=True)
                                        tweet_dt = pd.to_datetime(tweet_time.replace(' UTC', ''), utc=True)
                                        post_tweet_data = df[df['hour'] >= tweet_dt].sort_values('hour')
                                        pre_tweet_data = df[df['hour'] < tweet_dt].sort_values('hour')
                                        
                                        
                                        if not post_tweet_data.empty and not pre_tweet_data.empty:
                                            # Get prices right before and after tweet
                                            price_before = pre_tweet_data.iloc[-1]['avg_token_price_usd']
                                            price_after_1h = post_tweet_data.iloc[0]['avg_token_price_usd'] if len(post_tweet_data) > 0 else None
                                            price_after_24h = post_tweet_data.iloc[-1]['avg_token_price_usd'] if len(post_tweet_data) > 0 else None
                                            
                                            # Calculate changes
                                            if price_after_1h is not None:
                                                change_1h = ((price_after_1h - price_before) / price_before) * 100
                                            else:
                                                change_1h = None
                                                
                                            if price_after_24h is not None:
                                                change_24h = ((price_after_24h - price_before) / price_before) * 100
                                            else:
                                                change_24h = None
                                            
                                            # Display metrics
                                            st.markdown("#### Price Impact Analysis")
                                            
                                            m1, m2, m3 = st.columns(3)
                                            
                                            m1.metric(
                                                "Price Before Tweet", 
                                                f"${price_before:.6f}"
                                            )
                                            
                                            if price_after_1h is not None:
                                                m2.metric(
                                                    "First Price After Tweet", 
                                                    f"${price_after_1h:.6f}", 
                                                    f"{change_1h:.2f}%"
                                                )
                                            
                                            if price_after_24h is not None:
                                                m3.metric(
                                                    "Latest Price", 
                                                    f"${price_after_24h:.6f}", 
                                                    f"{change_24h:.2f}%"
                                                )
                                    else:
                                        st.info(f"No price data found for address {address}")
                        else:
                            st.info("No Flipside data was found for the specified addresses and time ranges.")
                    else:
                        st.info(f"No Solana contract addresses found in tweets by @{username} in the last {timeframe} hours.")

# Add explanation section
with st.expander("About This App"):
    st.markdown("""
    ## How it works
    
    This app analyzes tweets from a specified Twitter user to find Solana contract addresses. 
    It then queries price data from Flipside to track how these tokens performed before and after being mentioned.
    
    ### Features:
    
    1. **Twitter Analysis**: Extracts Solana contract addresses from tweets
    2. **Price Tracking**: Shows price movements before and after tweets
    3. **Trading Activity**: Visualizes swap counts to measure trading volume
    4. **Impact Analysis**: Calculates percentage changes in token prices
    
    ### How to use:
    
    1. Enter a Twitter username (without @)
    2. Select the timeframe (in hours, up to 24)
    3. Click "Analyze Tweets"
    4. View the results in the tabs for each found address
    """)

# Add footer
st.markdown("---")
st.markdown(
    """
    <div style="text-align: center">
        <p>Developed with ❤️ | Data provided by Twitter API and Flipside</p>
    </div>
    """, 
    unsafe_allow_html=True
)