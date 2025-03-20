"""
Data merging module for Venmito project.

This module provides classes for merging data from various sources
into coherent datasets for analytics.
"""

import logging
import os
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Union, Tuple

import pandas as pd
import numpy as np

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MergeError(Exception):
    """Exception raised for data merging errors."""
    pass


class DataMerger(ABC):
    """Abstract base class for data mergers."""
    
    def __init__(self):
        """Initialize the merger."""
        self.merge_errors = []
        logger.info("Initialized data merger")
    
    @abstractmethod
    def merge(self) -> Dict[str, pd.DataFrame]:
        """
        Merge data from different sources.
        
        Returns:
            Dict[str, pd.DataFrame]: Dictionary of merged DataFrames
        """
        pass
    
    def get_errors(self) -> List[str]:
        """
        Get all merging errors.
        
        Returns:
            List[str]: List of merging error messages
        """
        return self.merge_errors
    
    def _add_error(self, message: str) -> None:
        """
        Add an error message to the list of merging errors.
        
        Args:
            message (str): Error message
        """
        self.merge_errors.append(message)
        logger.warning(f"Merging error: {message}")
    
    def _save_dataframe(self, df: pd.DataFrame, name: str, output_dir: str) -> None:
        """
        Save a DataFrame to CSV.
        
        Args:
            df (pd.DataFrame): DataFrame to save
            name (str): Name to use for the file
            output_dir (str): Directory to save to
        """
        try:
            # Ensure output directory exists
            os.makedirs(output_dir, exist_ok=True)
            
            # Save the DataFrame
            output_path = os.path.join(output_dir, f"{name}.csv")
            df.to_csv(output_path, index=False)
            logger.info(f"Saved {name} to {output_path}")
        except Exception as e:
            self._add_error(f"Failed to save {name}: {str(e)}")


class PeopleMerger(DataMerger):
    """Merger for people data from different sources."""
    
    def __init__(self, people_json_df: pd.DataFrame, people_yml_df: pd.DataFrame):
        """
        Initialize the merger with people data from JSON and YAML sources.
        
        Args:
            people_json_df (pd.DataFrame): People data from JSON
            people_yml_df (pd.DataFrame): People data from YAML
        """
        super().__init__()
        self.people_json_df = people_json_df
        self.people_yml_df = people_yml_df
    
    def merge(self) -> Dict[str, pd.DataFrame]:
        """
        Merge people data from JSON and YAML sources.
        
        Returns:
            Dict[str, pd.DataFrame]: Dictionary with the merged people DataFrame
        """
        try:
            logger.info("Merging people data...")
            
            # Check for overlapping users
            json_ids = set(self.people_json_df['user_id']) if 'user_id' in self.people_json_df.columns else set()
            yml_ids = set(self.people_yml_df['user_id']) if 'user_id' in self.people_yml_df.columns else set()
            
            overlap = json_ids.intersection(yml_ids)
            if overlap:
                logger.info(f"Found {len(overlap)} overlapping users in JSON and YAML data")
            
            # Columns that should be in both dataframes for a proper merge
            common_columns = [
                'user_id', 'first_name', 'last_name', 'email', 'phone', 
                'city', 'country', 'devices'
            ]
            
            # Ensure all common columns exist in both dataframes
            for df, source in [(self.people_json_df, 'JSON'), (self.people_yml_df, 'YAML')]:
                missing_columns = [col for col in common_columns if col not in df.columns]
                if missing_columns:
                    logger.warning(f"Missing columns in {source} data: {missing_columns}")
                    for col in missing_columns:
                        df[col] = None
            
            # Merge dataframes, preferring JSON data for overlapping users
            # Using outer join to keep all users from both sources
            merged_df = pd.merge(
                self.people_json_df, 
                self.people_yml_df,
                on=common_columns,
                how='outer',
                suffixes=('_json', '_yml')
            )
            
            logger.info(f"Merged people data with shape {merged_df.shape}")
            
            return {'people': merged_df}
            
        except Exception as e:
            error_msg = f"Unexpected error in people data merging: {str(e)}"
            logger.error(error_msg)
            self._add_error(error_msg)
            return {'people': pd.DataFrame()}


class UserReferencesMerger(DataMerger):
    """Merger for adding user_id references to promotions and transactions."""
    
    def __init__(self, people_df: pd.DataFrame, promotions_df: pd.DataFrame, 
                transactions_df: Optional[pd.DataFrame] = None):
        """
        Initialize the merger with people, promotions, and transactions data.
        
        Args:
            people_df (pd.DataFrame): People data
            promotions_df (pd.DataFrame): Promotions data
            transactions_df (pd.DataFrame, optional): Transactions data
        """
        super().__init__()
        self.people_df = people_df
        self.promotions_df = promotions_df
        self.transactions_df = transactions_df
    
    def _add_user_references_to_promotions(self) -> pd.DataFrame:
        """
        Add user_id references to promotions based on email or phone.
        
        Returns:
            pd.DataFrame: Promotions DataFrame with user_id references
        """
        promotions_df = self.promotions_df.copy()
        
        # Check if user_id already exists and is populated
        if 'user_id' in promotions_df.columns and not promotions_df['user_id'].isna().all():
            logger.info("Promotions already have user_id references")
            return promotions_df
        
        # Initialize user_id column if it doesn't exist
        if 'user_id' not in promotions_df.columns:
            promotions_df['user_id'] = None
        
        # Check for email reference
        if 'client_email' in promotions_df.columns and 'email' in self.people_df.columns:
            email_map = self.people_df.set_index('email')['user_id'].to_dict()
            
            for index, row in promotions_df.iterrows():
                if pd.notna(row['client_email']) and row['client_email'] in email_map:
                    promotions_df.at[index, 'user_id'] = email_map[row['client_email']]
            
            # Drop client_email column since we now have user_id
            promotions_df.drop(columns=['client_email'], inplace=True, errors='ignore')
            logger.info("Added user references to promotions based on email")
        
        # Check for phone reference
        if 'telephone' in promotions_df.columns and 'phone' in self.people_df.columns:
            phone_map = self.people_df.set_index('phone')['user_id'].to_dict()
            
            # For rows that still have no user_id, try to find by phone
            mask = promotions_df['user_id'].isna()
            for index, row in promotions_df[mask].iterrows():
                if pd.notna(row['telephone']) and row['telephone'] in phone_map:
                    promotions_df.at[index, 'user_id'] = phone_map[row['telephone']]
            
            # Drop telephone column since we now have user_id
            promotions_df.drop(columns=['telephone'], inplace=True, errors='ignore')
            logger.info("Added user references to promotions based on phone")
        
        # Log warning for promotions without user_id
        missing_user_id = promotions_df['user_id'].isna().sum()
        if missing_user_id > 0:
            self._add_error(f"Could not find user_id for {missing_user_id} promotions")
        
        return promotions_df
    
    def _add_user_references_to_transactions(self) -> pd.DataFrame:
        """
        Add user_id references to transactions based on phone.
        
        Returns:
            pd.DataFrame: Transactions DataFrame with user_id references
        """
        if self.transactions_df is None:
            logger.info("No transactions data provided for user reference merging")
            return pd.DataFrame()
        
        transactions_df = self.transactions_df.copy()
        
        # Check if user_id already exists and is populated
        if 'user_id' in transactions_df.columns and not transactions_df['user_id'].isna().all():
            logger.info("Transactions already have user_id references")
            return transactions_df
        
        # Initialize user_id column if it doesn't exist
        if 'user_id' not in transactions_df.columns:
            transactions_df['user_id'] = None
        
        # Check for phone reference
        if 'phone' in transactions_df.columns and 'phone' in self.people_df.columns:
            phone_map = self.people_df.set_index('phone')['user_id'].to_dict()
            
            for index, row in transactions_df.iterrows():
                if pd.notna(row['phone']) and row['phone'] in phone_map:
                    transactions_df.at[index, 'user_id'] = phone_map[row['phone']]
            
            # Drop phone column since we now have user_id
            transactions_df.drop(columns=['phone'], inplace=True, errors='ignore')
            logger.info("Added user references to transactions based on phone")
        
        # Log warning for transactions without user_id
        missing_user_id = transactions_df['user_id'].isna().sum()
        if missing_user_id > 0:
            self._add_error(f"Could not find user_id for {missing_user_id} transactions")
        
        return transactions_df
    
    def merge(self) -> Dict[str, pd.DataFrame]:
        """
        Merge user references into promotions and transactions.
        
        Returns:
            Dict[str, pd.DataFrame]: Dictionary with updated DataFrames
        """
        try:
            logger.info("Adding user references to related data...")
            
            result = {}
            
            # Add user references to promotions
            promotions_df = self._add_user_references_to_promotions()
            result['promotions'] = promotions_df
            
            # Add user references to transactions if available
            if self.transactions_df is not None:
                transactions_df = self._add_user_references_to_transactions()
                result['transactions'] = transactions_df
            
            logger.info("Completed adding user references")
            return result
            
        except Exception as e:
            error_msg = f"Unexpected error in user reference merging: {str(e)}"
            logger.error(error_msg)
            self._add_error(error_msg)
            return {'promotions': self.promotions_df, 'transactions': self.transactions_df}


class UserTransactionsMerger(DataMerger):
    """Merger for creating user-level transaction summaries."""
    
    def __init__(self, transactions_df: pd.DataFrame, people_df: pd.DataFrame):
        """
        Initialize the merger with transactions and people data.
        
        Args:
            transactions_df (pd.DataFrame): Transactions data
            people_df (pd.DataFrame): People data
        """
        super().__init__()
        self.transactions_df = transactions_df
        self.people_df = people_df
    
    def _get_favorite_store(self, stores: pd.Series) -> str:
        """
        Get the most frequent store for a user.
        
        Args:
            stores (pd.Series): Series of stores
        
        Returns:
            str: Most frequent store or None if no data
        """
        if stores.empty:
            return None
        
        mode = stores.mode()
        return mode.iloc[0] if not mode.empty else None
    
    def _get_favorite_item(self, items: pd.Series) -> str:
        """
        Get the most frequently purchased item for a user.
        
        Args:
            items (pd.Series): Series of items
        
        Returns:
            str: Most frequent item or None if no data
        """
        if items.empty:
            return None
        
        mode = items.mode()
        return mode.iloc[0] if not mode.empty else None
    
    def merge(self) -> Dict[str, pd.DataFrame]:
        """
        Create user-level transaction summaries.
        
        Returns:
            Dict[str, pd.DataFrame]: Dictionary with user_transactions DataFrame
        """
        try:
            logger.info("Creating user-level transaction summaries...")
            
            # Ensure required columns exist
            required_columns = ['user_id', 'transaction_id', 'price', 'item', 'store']
            if not all(col in self.transactions_df.columns for col in required_columns):
                missing = [col for col in required_columns if col not in self.transactions_df.columns]
                self._add_error(f"Missing required columns for user transactions summary: {missing}")
                return {'user_transactions': pd.DataFrame()}
            
            # Group transactions by user_id
            aggregated_df = self.transactions_df.groupby('user_id').agg(
                total_spent=('price', 'sum'),
                transaction_count=('transaction_id', 'nunique'),
                favorite_store=('store', self._get_favorite_store),
                favorite_item=('item', self._get_favorite_item)
            )
            
            # Reset index to make user_id a column
            aggregated_df = aggregated_df.reset_index()
            
            # Merge with people data to ensure all users are included
            result_df = pd.merge(self.people_df[['user_id']], aggregated_df, on='user_id', how='left')
            
            # Fill missing values for users with no transactions
            result_df['total_spent'] = result_df['total_spent'].fillna(0)
            result_df['transaction_count'] = result_df['transaction_count'].fillna(0).astype(int)
            
            logger.info(f"Created user transaction summaries with shape {result_df.shape}")
            
            return {'user_transactions': result_df}
            
        except Exception as e:
            error_msg = f"Unexpected error in user transactions merging: {str(e)}"
            logger.error(error_msg)
            self._add_error(error_msg)
            return {'user_transactions': pd.DataFrame()}


class UserTransfersMerger(DataMerger):
    """Merger for creating user-level transfer summaries."""
    
    def __init__(self, transfers_df: pd.DataFrame, people_df: pd.DataFrame):
        """
        Initialize the merger with transfers and people data.
        
        Args:
            transfers_df (pd.DataFrame): Transfers data
            people_df (pd.DataFrame): People data
        """
        super().__init__()
        self.transfers_df = transfers_df
        self.people_df = people_df
    
    def merge(self) -> Dict[str, pd.DataFrame]:
        """
        Create user-level transfer summaries.
        
        Returns:
            Dict[str, pd.DataFrame]: Dictionary with user_transfers DataFrame
        """
        try:
            logger.info("Creating user-level transfer summaries...")
            
            # Ensure required columns exist
            required_columns = ['transfer_id', 'sender_id', 'recipient_id', 'amount']
            if not all(col in self.transfers_df.columns for col in required_columns):
                missing = [col for col in required_columns if col not in self.transfers_df.columns]
                self._add_error(f"Missing required columns for user transfers summary: {missing}")
                return {'user_transfers': pd.DataFrame()}
            
            # Calculate sent amounts
            sent_total = self.transfers_df.groupby('sender_id')['amount'].sum()
            sent_count = self.transfers_df.groupby('sender_id')['transfer_id'].nunique()
            
            # Calculate received amounts
            received_total = self.transfers_df.groupby('recipient_id')['amount'].sum()
            received_count = self.transfers_df.groupby('recipient_id')['transfer_id'].nunique()
            
            # Calculate net transferred
            net_transferred = pd.Series(dtype='float64')
            all_user_ids = set(self.transfers_df['sender_id']).union(set(self.transfers_df['recipient_id']))
            for user_id in all_user_ids:
                sent = sent_total.get(user_id, 0)
                received = received_total.get(user_id, 0)
                net_transferred[user_id] = received - sent
            
            # Create the result DataFrame
            result_df = pd.DataFrame({
                'user_id': list(all_user_ids)
            })
            
            # Add calculated columns
            result_df['total_sent'] = result_df['user_id'].map(sent_total).fillna(0)
            result_df['total_received'] = result_df['user_id'].map(received_total).fillna(0)
            result_df['net_transferred'] = result_df['user_id'].map(net_transferred).fillna(0)
            result_df['sent_count'] = result_df['user_id'].map(sent_count).fillna(0).astype(int)
            result_df['received_count'] = result_df['user_id'].map(received_count).fillna(0).astype(int)
            result_df['transfer_count'] = result_df['sent_count'] + result_df['received_count']
            
            # Merge with people data to ensure all users are included
            result_df = pd.merge(self.people_df[['user_id']], result_df, on='user_id', how='left')
            
            # Fill missing values for users with no transfers
            for col in ['total_sent', 'total_received', 'net_transferred']:
                result_df[col] = result_df[col].fillna(0)
            
            for col in ['sent_count', 'received_count', 'transfer_count']:
                result_df[col] = result_df[col].fillna(0).astype(int)
            
            logger.info(f"Created user transfer summaries with shape {result_df.shape}")
            
            return {'user_transfers': result_df}
            
        except Exception as e:
            error_msg = f"Unexpected error in user transfers merging: {str(e)}"
            logger.error(error_msg)
            self._add_error(error_msg)
            return {'user_transfers': pd.DataFrame()}


class ItemSummaryMerger(DataMerger):
    """Merger for creating item-level summaries."""
    
    def __init__(self, transactions_df: pd.DataFrame):
        """
        Initialize the merger with transactions data.
        
        Args:
            transactions_df (pd.DataFrame): Transactions data
        """
        super().__init__()
        self.transactions_df = transactions_df
    
    def merge(self) -> Dict[str, pd.DataFrame]:
        """
        Create item-level summaries.
        
        Returns:
            Dict[str, pd.DataFrame]: Dictionary with item_summary DataFrame
        """
        try:
            logger.info("Creating item-level summaries...")
            
            # Ensure required columns exist
            required_columns = ['item', 'price', 'quantity', 'transaction_id']
            if not all(col in self.transactions_df.columns for col in required_columns):
                missing = [col for col in required_columns if col not in self.transactions_df.columns]
                self._add_error(f"Missing required columns for item summary: {missing}")
                return {'item_summary': pd.DataFrame()}
            
            # Group transactions by item
            aggregated_df = self.transactions_df.groupby('item').agg(
                total_revenue=('price', 'sum'),
                items_sold=('quantity', 'sum'),
                transaction_count=('transaction_id', 'nunique')
            )
            
            # Calculate average price per item
            aggregated_df['average_price'] = (aggregated_df['total_revenue'] / aggregated_df['items_sold']).round(2)
            
            # Reset index to make item a column
            aggregated_df = aggregated_df.reset_index()
            
            logger.info(f"Created item summaries with shape {aggregated_df.shape}")
            
            return {'item_summary': aggregated_df}
            
        except Exception as e:
            error_msg = f"Unexpected error in item summary merging: {str(e)}"
            logger.error(error_msg)
            self._add_error(error_msg)
            return {'item_summary': pd.DataFrame()}


class StoreSummaryMerger(DataMerger):
    """Merger for creating store-level summaries."""
    
    def __init__(self, transactions_df: pd.DataFrame):
        """
        Initialize the merger with transactions data.
        
        Args:
            transactions_df (pd.DataFrame): Transactions data
        """
        super().__init__()
        self.transactions_df = transactions_df
    
    def _get_most_sold_item(self, store: str) -> str:
        """
        Get the most sold item for a store based on quantity.
        
        Args:
            store (str): Store name
        
        Returns:
            str: Most sold item or None if no data
        """
        store_data = self.transactions_df[self.transactions_df['store'] == store]
        if store_data.empty:
            return None
        
        item_qty = store_data.groupby('item')['quantity'].sum()
        return item_qty.idxmax() if not item_qty.empty else None
    
    def _get_most_profitable_item(self, store: str) -> str:
        """
        Get the most profitable item for a store based on total revenue.
        
        Args:
            store (str): Store name
        
        Returns:
            str: Most profitable item or None if no data
        """
        store_data = self.transactions_df[self.transactions_df['store'] == store]
        if store_data.empty:
            return None
        
        item_revenue = store_data.groupby('item')['price'].sum()
        return item_revenue.idxmax() if not item_revenue.empty else None
    
    def merge(self) -> Dict[str, pd.DataFrame]:
        """
        Create store-level summaries.
        
        Returns:
            Dict[str, pd.DataFrame]: Dictionary with store_summary DataFrame
        """
        try:
            logger.info("Creating store-level summaries...")
            
            # Ensure required columns exist
            required_columns = ['store', 'item', 'price', 'quantity', 'transaction_id']
            if not all(col in self.transactions_df.columns for col in required_columns):
                missing = [col for col in required_columns if col not in self.transactions_df.columns]
                self._add_error(f"Missing required columns for store summary: {missing}")
                return {'store_summary': pd.DataFrame()}
            
            # Group transactions by store
            aggregated_df = self.transactions_df.groupby('store').agg(
                total_revenue=('price', 'sum'),
                items_sold=('quantity', 'sum'),
                total_transactions=('transaction_id', 'nunique')
            )
            
            # Calculate average transaction value
            aggregated_df['average_transaction_value'] = (
                aggregated_df['total_revenue'] / aggregated_df['total_transactions']
            ).round(2)
            
            # Add most sold and most profitable items
            stores = aggregated_df.index.tolist()
            
            most_sold_items = []
            most_profitable_items = []
            
            for store in stores:
                most_sold_items.append(self._get_most_sold_item(store))
                most_profitable_items.append(self._get_most_profitable_item(store))
            
            aggregated_df['most_sold_item'] = most_sold_items
            aggregated_df['most_profitable_item'] = most_profitable_items
            
            # Reset index to make store a column
            aggregated_df = aggregated_df.reset_index()
            
            logger.info(f"Created store summaries with shape {aggregated_df.shape}")
            
            return {'store_summary': aggregated_df}
            
        except Exception as e:
            error_msg = f"Unexpected error in store summary merging: {str(e)}"
            logger.error(error_msg)
            self._add_error(error_msg)
            return {'store_summary': pd.DataFrame()}


class MainDataMerger(DataMerger):
    """Main merger class to orchestrate the entire merging process."""
    
    def __init__(self, 
                people_json_df: pd.DataFrame, 
                people_yml_df: pd.DataFrame,
                promotions_df: pd.DataFrame,
                transfers_df: pd.DataFrame,
                transactions_df: Optional[pd.DataFrame] = None,
                output_dir: str = 'data/processed'):
        """
        Initialize the main merger with all data sources.
        
        Args:
            people_json_df (pd.DataFrame): People data from JSON
            people_yml_df (pd.DataFrame): People data from YAML
            promotions_df (pd.DataFrame): Promotions data
            transfers_df (pd.DataFrame): Transfers data
            transactions_df (pd.DataFrame, optional): Transactions data
            output_dir (str): Directory to save processed data
        """
        super().__init__()
        self.people_json_df = people_json_df
        self.people_yml_df = people_yml_df
        self.promotions_df = promotions_df
        self.transfers_df = transfers_df
        self.transactions_df = transactions_df
        self.output_dir = output_dir
    
    def merge(self) -> Dict[str, pd.DataFrame]:
        """
        Merge people data from JSON and YAML sources.
        
        Returns:
            Dict[str, pd.DataFrame]: Dictionary with the merged people DataFrame
        """
        try:
            logger.info("Merging people data...")
            
            # Convert any list columns to strings to avoid "unhashable type: 'list'" error
            people_json_df = self.people_json_df.copy()
            people_yml_df = self.people_yml_df.copy()
            
            for df in [people_json_df, people_yml_df]:
                for col in df.columns:
                    # Check if column contains lists
                    if df[col].apply(lambda x: isinstance(x, list)).any():
                        # Convert lists to comma-separated strings
                        df[col] = df[col].apply(lambda x: ', '.join(map(str, x)) if isinstance(x, list) else x)
            
            # Check for overlapping users
            json_ids = set(people_json_df['user_id']) if 'user_id' in people_json_df.columns else set()
            yml_ids = set(people_yml_df['user_id']) if 'user_id' in people_yml_df.columns else set()
            
            overlap = json_ids.intersection(yml_ids)
            if overlap:
                logger.info(f"Found {len(overlap)} overlapping users in JSON and YAML data")
            
            # Columns that should be in both dataframes for a proper merge
            common_columns = [
                'user_id', 'first_name', 'last_name', 'email', 'phone', 
                'city', 'country', 'devices'
            ]
            
            # Ensure all common columns exist in both dataframes
            for df, source in [(people_json_df, 'JSON'), (people_yml_df, 'YAML')]:
                missing_columns = [col for col in common_columns if col not in df.columns]
                if missing_columns:
                    logger.warning(f"Missing columns in {source} data: {missing_columns}")
                    for col in missing_columns:
                        df[col] = None
            
            # Use concat + drop_duplicates instead of merge for more robustness
            merged_df = pd.concat([people_json_df, people_yml_df], ignore_index=True)
            
            # Remove duplicates based on user_id (keeping the first occurrence, which will be from JSON)
            if 'user_id' in merged_df.columns:
                merged_df = merged_df.drop_duplicates(subset=['user_id'], keep='first')
            
            logger.info(f"Merged people data with shape {merged_df.shape}")
            
            return {'people': merged_df}
        
        except Exception as e:
            error_msg = f"Unexpected error in people data merging: {str(e)}"
            logger.error(error_msg)
            self._add_error(error_msg)
            return {'people': pd.DataFrame()}