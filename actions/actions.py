from typing import Any, Text, Dict, List
from rasa_sdk import Action, Tracker
from rasa_sdk import events
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import FollowupAction, SlotSet  # Corrected import
import pandas as pd
import os
import json
import uuid
import requests
import time
import random

class JewelryAction(Action):
    """Base class for jewelry-related actions with shared functionality"""
    
    PRODUCTS_PER_PAGE = 5

    def __init__(self):
        self.df = None
        self.current_dir = os.path.dirname(os.path.abspath(__file__))
        self.csv_path = os.path.join(self.current_dir, 'jewelry_data.csv')
        self.filtered_data = None
        self.current_page = 0

    def name(self) -> Text:
        return "jewelry_action_base"

    def load_data(self):
        """Load the CSV data if not already loaded"""
        if self.df is None:
            if not os.path.exists(self.csv_path):
                raise FileNotFoundError(f"CSV file not found at: {self.csv_path}")
            self.df = pd.read_csv(self.csv_path)

    def get_base_filtered_data(self, main_category: str, sub_category: str) -> pd.DataFrame:
        """Get data filtered by main category and sub category"""
        self.load_data()
        return self.df[
            (self.df['main_category'] == main_category) & 
            (self.df['sub_category'] == sub_category)
        ]

    def apply_view_filter(self, base_data: pd.DataFrame, view_type: str) -> pd.DataFrame:
        """Apply bestseller or discount filter based on view type"""
        if view_type == "bestseller":
            return base_data[base_data['is_bestseller'] == 1]
        elif view_type == "discount":
            return base_data[base_data['Has_Discount'] == 1]
        else:  # regular view
            return base_data

    def get_page_slice(self, data: pd.DataFrame, page: int) -> pd.DataFrame:
        """Get a slice of data for the current page"""
        start_idx = page * self.PRODUCTS_PER_PAGE
        end_idx = min(start_idx + self.PRODUCTS_PER_PAGE, len(data))  # Ensure we don't exceed data size
        return data.iloc[start_idx:end_idx]

    def format_product_message(self, products: pd.DataFrame, 
                             page: int, total_count: int,
                             view_type: str = "products") -> str:
        """Format product information into a readable message"""
        if products.empty:
            return "No products found."

        start_idx = (page * self.PRODUCTS_PER_PAGE) + 1
        end_idx = start_idx + len(products) - 1
        
        # Determine display type
        display_type = {
            "bestseller": "bestsellers",
            "discount": "discounted products",
            "regular": "products"
        }.get(view_type, "products")
        
        message = f"Showing {start_idx}-{end_idx} of {total_count} {display_type}:\n\n"
        
        for i, (_, product) in enumerate(products.iterrows(), start=1):
            product_idx = start_idx + i - 1  # Calculate unique product index
            
            product_name = product['Product_Name']
            base_price = product['Base_Price_Without_Addon']
            discounted_price = product.get('Discounted_Base_Price_Without_Addon', None)
            
            message += f"🏆 {product_name}\n"
            message += f"💎 {product['Definition']}\n"
            message += f"💰 Base Price: ₹{base_price}\n"
            
            if pd.notna(discounted_price):
                message += f"🏷️ Discounted Price: ₹{discounted_price}\n"
            
            message += f"⌛ Delivery Time: {product['Delivery_Time']}\n"
            message += f"✨ Available Options: {product['Available_Options']}\n"
            message += f"🔗 Product Link: {product['Product_URL']}\n\n"
        
        return message

    def create_product_buttons(self, products: pd.DataFrame, page: int) -> List[Dict]:
        """Create buttons for each product in the current page"""
        if products.empty:
            return []
            
        product_buttons = []
        start_idx = (page * self.PRODUCTS_PER_PAGE) + 1
        
        for i, (_, product) in enumerate(products.iterrows(), start=0):  # Start from 0 instead of 1
            product_idx = start_idx + i  # Calculate correct product index
            product_name = product['Product_Name']
            
            # Create a button for this product
            product_buttons.append({
                "title": f"🛒 Add {product_name} to Cart",
                "payload": f"/add_to_cart{{\"product_idx\": \"{product_idx}\"}}"
            })
        
        return product_buttons

    def create_response_buttons(self, current_page: int, total_pages: int, total_count: int, 
                                view_type: str) -> List[Dict]:
        """Create navigation buttons based on the current state"""
        buttons = []
        
        # Check if we're on the last page
        is_last_page = (current_page >= total_pages - 1)
        
        if not is_last_page:
            # Normal pagination for non-last pages
            buttons.append({
                "title": "📥 Show More",
                "payload": "/show_more"
            })
            
            # Add view switching buttons
            if view_type == "bestseller":
                buttons.extend([
                    {"title": "Show Discounted", "payload": "/show_discounted"},
                    {"title": "Show Regular", "payload": "/show_regular"}
                ])
            elif view_type == "discount":
                buttons.extend([
                    {"title": "Show Bestsellers", "payload": "/show_bestsellers"},
                    {"title": "Show Regular", "payload": "/show_regular"}
                ])
            else:  # regular view
                buttons.extend([
                    {"title": "Show Bestsellers", "payload": "/show_bestsellers"},
                    {"title": "Show Discounted", "payload": "/show_discounted"}
                ])
        else:
            # We're on the last page - add "Check Other Options" button
            buttons.append({
                "title": "✨ Check Other Options",
                "payload": "/reset_category_flow"  # This will trigger the exception message
            })
        
        # Always add View Cart button
        buttons.append({
            "title": "🛒 View Cart",
            "payload": "/view_cart"
        })
        
        # Always add category change option
        buttons.append({
            "title": "🔄 View Different Category",
            "payload": "/reset_category_flow"                                                                                                                                   
        })
        
        return buttons
    
    def get_last_view_action(self, tracker: Tracker) -> str:
        """Get the last view action that was executed"""
        view_actions = ["action_show_bestsellers", "action_show_discounted", "action_show_regular"]
        
        # Check actions in reverse order
        actions_history = [event for event in tracker.events if event.get('event') == 'action']
        for action in reversed(actions_history):
            action_name = action.get('name', '')
            if action_name in view_actions:
                return action_name
        
        return None

    def is_switching_views(self, tracker: Tracker, current_action: str) -> bool:
        """Check if we're switching from one view to another"""
        last_view = self.get_last_view_action(tracker)
        return last_view is not None and last_view != current_action
    
    def get_total_pages(self, main_category: str, sub_category: str, view_type: str) -> int:
        """Calculate total pages for a given view type"""
        base_data = self.get_base_filtered_data(main_category, sub_category)
        filtered_data = self.apply_view_filter(base_data, view_type)
        total_count = len(filtered_data)
        return (total_count + self.PRODUCTS_PER_PAGE - 1) // self.PRODUCTS_PER_PAGE
    
    def reset_page_state(self, tracker: Tracker) -> List[Dict[Text, Any]]:
        """Reset page state and provide consistent reset events"""
        return [
            SlotSet("current_page", 0),
            SlotSet("last_view_type", tracker.get_slot('view_type')),
            SlotSet("view_type", None)
        ]
    
    def get_cart(self, tracker: Tracker) -> List[Dict]:
        """Retrieve the current cart from a slot"""
        cart_json = tracker.get_slot('shopping_cart')
        if not cart_json:
            return []
        
        try:
            return json.loads(cart_json)
        except:
            return []
    
    def set_cart(self, cart_items: List[Dict]) -> Dict[Text, Any]:
        """Convert cart to JSON and create a slot event"""
        return SlotSet('shopping_cart', json.dumps(cart_items))
    
    def get_last_page(self, tracker: Tracker) -> int:
        """Safely get the last page number from slots"""
        try:
            last_page = tracker.get_slot('last_page')
            return int(last_page) if last_page is not None else 0
        except (TypeError, ValueError):
            return 0
    
class ActionShowBestsellers(JewelryAction):
    def name(self) -> Text:
        return "action_show_bestsellers"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        try:
            # Check if we're continuing shopping and already have a page
            is_continuing = tracker.get_slot('intent') == 'continue_shopping'
            current_page = int(tracker.get_slot('current_page') or 0)
            
            # If continuing and page > 0, use ActionShowMore to go to that page
            if is_continuing and current_page > 0:
                print(f"Continuing bestseller browsing at page {current_page}")
                return ActionShowMore().run(dispatcher, tracker, domain)
            
            # Otherwise start from page 0
            # Reset state first
            reset_events = self.reset_page_state(tracker)
            
            # Check if we're already in a bestseller view (to prevent double execution)
            if self.is_switching_views(tracker, "action_show_bestsellers"):
                print("View switching detected: -> bestsellers")
            else:
                print("Direct bestseller view")
                
            main_category = tracker.get_slot('main_category')
            sub_category = tracker.get_slot('sub_category')
            
            # Debug information
            print(f"ActionShowBestsellers: RESETTING page counter to 0")
            print(f"Main category: {main_category}, Sub category: {sub_category}")
            
            # Get base filtered data
            base_data = self.get_base_filtered_data(main_category, sub_category)
            
            # Apply bestseller filter
            bestsellers = self.apply_view_filter(base_data, "bestseller")
            
            if bestsellers.empty:
                message = (
                    f"Sorry, we don't have any bestsellers in {main_category} {sub_category} "
                    f"at the moment.\n\nWould you like to:"
                )
                buttons = [
                    {"title": "Show discounted products", "payload": "/show_discounted"},
                    {"title": "Show regular products", "payload": "/show_regular"},
                    {"title": "View Cart", "payload": "/view_cart"},
                    {"title": "View different category", "payload": "/reset_category_flow"}
                ]
                dispatcher.utter_message(text=message, buttons=buttons)
                return reset_events + [
                    SlotSet("view_type", None)
                ]

            # Get first page of data
            first_page = self.get_page_slice(bestsellers, 0)
            total_count = len(bestsellers)
            total_pages = (total_count + self.PRODUCTS_PER_PAGE - 1) // self.PRODUCTS_PER_PAGE

            # Format product message
            message = self.format_product_message(first_page, 0, total_count, "bestseller")
            
            # If this is the last page (only 1 page total), add "You've seen all" message
            if total_pages == 1:
                message += "\nYou've seen all the available bestsellers in this category."

            # Create product buttons
            product_buttons = self.create_product_buttons(first_page, 0)
            
            # Generate navigation buttons
            navigation_buttons = self.create_response_buttons(0, total_pages, total_count, "bestseller")
            
            # Combine all buttons
            all_buttons = product_buttons + navigation_buttons
            
            # Send a single message with all buttons
            dispatcher.utter_message(text=message, buttons=all_buttons)
            
            return reset_events + [
                SlotSet("current_page", 0),
                SlotSet("view_type", "bestseller"),
                SlotSet("intent", "show_bestsellers"),
                SlotSet("shopping_context", "product_browsing"),
                SlotSet("last_page", 0)
            ]

        except Exception as e:
            print(f"Error in ActionShowBestsellers: {str(e)}")
            dispatcher.utter_message(
                text="Sorry, I encountered an error while fetching bestsellers. Would you like to try something else?",
                buttons=[
                    {"title": "Show discounted products", "payload": "/show_discounted"},
                    {"title": "Show regular products", "payload": "/show_regular"},
                    {"title": "View Cart", "payload": "/view_cart"},
                    {"title": "View different category", "payload": "/reset_category_flow"}
                ]
            )
            # Return reset events in case of an error
            return self.reset_page_state(tracker) + [
                SlotSet("view_type", None),
                SlotSet("shopping_context", None)
            ]
        
class ActionShowDiscounted(JewelryAction):
    def name(self) -> Text:
        return "action_show_discounted"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        try:
            # Check if we're continuing shopping and already have a page
            is_continuing = tracker.get_slot('intent') == 'continue_shopping'
            current_page = int(tracker.get_slot('current_page') or 0)
            
            # If continuing and page > 0, use ActionShowMore to go to that page
            if is_continuing and current_page > 0:
                print(f"Continuing discounted browsing at page {current_page}")
                return ActionShowMore().run(dispatcher, tracker, domain)
            
            # Otherwise start from page 0
            # Reset state first
            reset_events = self.reset_page_state(tracker)
            
            # Check if we're already in a discounted view (to prevent double execution)
            if self.is_switching_views(tracker, "action_show_discounted"):
                print("View switching detected: -> discounted")
            else:
                print("Direct discounted view")
                
            main_category = tracker.get_slot('main_category')
            sub_category = tracker.get_slot('sub_category')
            
            # Debug information
            print(f"ActionShowDiscounted: RESETTING page counter to 0")
            print(f"Main category: {main_category}, Sub category: {sub_category}")
            
            # Get base filtered data
            base_data = self.get_base_filtered_data(main_category, sub_category)
            
            # Apply discount filter
            discounted = self.apply_view_filter(base_data, "discount")
            
            if discounted.empty:
                message = (
                    f"Sorry, we don't have any discounted items in {main_category} "
                    f"{sub_category} at the moment.\n\nWould you like to:"
                )
                buttons = [
                    {"title": "Show bestsellers", "payload": "/show_bestsellers"},
                    {"title": "Show regular products", "payload": "/show_regular"},
                    {"title": "View Cart", "payload": "/view_cart"},
                    {"title": "View different category", "payload": "/reset_category_flow"}
                ]
                dispatcher.utter_message(text=message, buttons=buttons)
                return reset_events + [
                    SlotSet("view_type", None)
                ]

            # Get first page of data
            first_page = self.get_page_slice(discounted, 0)
            total_count = len(discounted)
            total_pages = (total_count + self.PRODUCTS_PER_PAGE - 1) // self.PRODUCTS_PER_PAGE

            # Format product message
            message = self.format_product_message(first_page, 0, total_count, "discount")
            
            # If this is the last page (only 1 page total), add "You've seen all" message
            if total_pages == 1:
                message += "\nYou've seen all the available discounted products in this category."

            # Create product buttons
            product_buttons = self.create_product_buttons(first_page, 0)
            
            # Generate navigation buttons
            navigation_buttons = self.create_response_buttons(0, total_pages, total_count, "discount")
            
            # Combine all buttons
            all_buttons = product_buttons + navigation_buttons
            
            # Send a single message with all buttons
            dispatcher.utter_message(text=message, buttons=all_buttons)
            
            return reset_events + [
                SlotSet("current_page", 0),
                SlotSet("view_type", "discount"),
                SlotSet("intent", "show_discounted"),
                SlotSet("shopping_context", "product_browsing"),
                SlotSet("last_page", 0)
            ]

        except Exception as e:
            print(f"Error in ActionShowDiscounted: {str(e)}")
            dispatcher.utter_message(
                text="Sorry, I encountered an error while fetching discounted products. Would you like to try something else?",
                buttons=[
                    {"title": "Show bestsellers", "payload": "/show_bestsellers"},
                    {"title": "Show regular products", "payload": "/show_regular"},
                    {"title": "View Cart", "payload": "/view_cart"},
                    {"title": "View different category", "payload": "/reset_category_flow"}
                ]
            )
            # Return reset events in case of an error
            return self.reset_page_state(tracker) + [
                SlotSet("view_type", None),
                SlotSet("shopping_context", None)
            ]


class ActionShowRegular(JewelryAction):
    def name(self) -> Text:
        return "action_show_regular"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        try:
            # Check if we're continuing shopping and already have a page
            is_continuing = tracker.get_slot('intent') == 'continue_shopping'
            current_page = int(tracker.get_slot('current_page') or 0)
            
            # If continuing and page > 0, use ActionShowMore to go to that page
            if is_continuing and current_page > 0:
                print(f"Continuing regular browsing at page {current_page}")
                return ActionShowMore().run(dispatcher, tracker, domain)
            
            # Otherwise start from page 0
            # Reset state first
            reset_events = self.reset_page_state(tracker)
            
            # Check if we're already in a regular view (to prevent double execution)
            if self.is_switching_views(tracker, "action_show_regular"):
                print("View switching detected: -> regular")
            else:
                print("Direct regular view")
                
            main_category = tracker.get_slot('main_category')
            sub_category = tracker.get_slot('sub_category')
            
            # Debug information
            print(f"ActionShowRegular: RESETTING page counter to 0")
            print(f"Main category: {main_category}, Sub category: {sub_category}")
            
            # Get base filtered data (no additional filters for regular view)
            regular_products = self.get_base_filtered_data(main_category, sub_category)
            
            if regular_products.empty:
                message = (
                    f"Sorry, we don't have any products in {main_category} "
                    f"{sub_category} at the moment.\n\nWould you like to explore a different category?"
                )
                dispatcher.utter_message(
                    text=message,
                    buttons=[
                        {"title": "Show bestsellers", "payload": "/show_bestsellers"},
                        {"title": "Show discounted products", "payload": "/show_discounted"},
                        {"title": "View Cart", "payload": "/view_cart"},
                        {"title": "View different category", "payload": "/reset_category_flow"}
                    ]
                )
                return reset_events + [
                    SlotSet("view_type", None)
                ]

            # Get first page of data
            first_page = self.get_page_slice(regular_products, 0)
            total_count = len(regular_products)
            total_pages = (total_count + self.PRODUCTS_PER_PAGE - 1) // self.PRODUCTS_PER_PAGE

            # Format product message
            message = self.format_product_message(first_page, 0, total_count, "regular")
            
            # If this is the last page (only 1 page total), add "You've seen all" message
            if total_pages == 1:
                message += "\nYou've seen all the available products in this category."

            # Create product buttons
            product_buttons = self.create_product_buttons(first_page, 0)
            
            # Generate navigation buttons
            navigation_buttons = self.create_response_buttons(0, total_pages, total_count, "regular")
            
            # Combine all buttons
            all_buttons = product_buttons + navigation_buttons
            
            # Send a single message with all buttons
            dispatcher.utter_message(text=message, buttons=all_buttons)
            
            return reset_events + [
                SlotSet("current_page", 0),
                SlotSet("view_type", "regular"),
                SlotSet("intent", "show_regular"),
                SlotSet("shopping_context", "product_browsing"),
                SlotSet("last_page", 0)
            ]

        except Exception as e:
            print(f"Error in ActionShowRegular: {str(e)}")
            dispatcher.utter_message(
                text="Sorry, I encountered an error while fetching products. Would you like to explore a different category?",
                buttons=[
                    {"title": "Show bestsellers", "payload": "/show_bestsellers"},
                    {"title": "Show discounted products", "payload": "/show_discounted"},
                    {"title": "View Cart", "payload": "/view_cart"},
                    {"title": "View different category", "payload": "/reset_category_flow"}
                ]
            )
            # Return reset events in case of an error
            return self.reset_page_state(tracker) + [
                SlotSet("view_type", None),
                SlotSet("shopping_context", None)
            ]


class ActionShowMore(JewelryAction):
    def name(self) -> Text:
        return "action_show_more"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        try:
            # Get view state
            view_type = tracker.get_slot('view_type')
            last_view_type = tracker.get_slot('last_view_type')
            main_category = tracker.get_slot('main_category')
            sub_category = tracker.get_slot('sub_category')
            current_page = int(tracker.get_slot('current_page') or 0)
            
            # Determine if this is a continuation from shopping
            is_continuing = tracker.get_slot('intent') == 'continue_shopping'
            
            print(f"ActionShowMore: current_page={current_page}, view_type={view_type}, continuing={is_continuing}")
            
            # Fix for missing view type
            if not view_type:
                view_type = last_view_type or "regular"
                print(f"Using fallback view_type: {view_type}")
            
            # Get filtered data
            base_data = self.get_base_filtered_data(main_category, sub_category)
            filtered_data = self.apply_view_filter(base_data, view_type)
            
            # Calculate pagination
            total_count = len(filtered_data)
            total_pages = (total_count + self.PRODUCTS_PER_PAGE - 1) // self.PRODUCTS_PER_PAGE
            
            # For continuation, we use the current page
            # For normal "show more", we increment the page
            if is_continuing:
                page_to_show = current_page
            else:
                page_to_show = current_page + 1
            
            # Ensure page_to_show doesn't exceed maximum pages
            page_to_show = min(page_to_show, total_pages - 1)
            
            # Check if we've reached the end
            if page_to_show >= total_pages:
                message = f"You've seen all the available {view_type} products in this category."
                
                # Buttons for switching to different views
                buttons = [
                    {"title": "Show Bestsellers", "payload": "/show_bestsellers"},
                    {"title": "Show Discounted", "payload": "/show_discounted"},
                    {"title": "Show Regular", "payload": "/show_regular"},
                    {"title": "View Cart", "payload": "/view_cart"},
                    {"title": "Explore Products", "payload": "/explore_products"}
                ]
                
                dispatcher.utter_message(text=message, buttons=buttons)
                
                # Keep the current view information
                return [
                    SlotSet("current_page", current_page),
                    SlotSet("view_type", view_type),
                    SlotSet("shopping_context", "product_browsing"),
                    SlotSet("last_page", current_page)
                ]
            
            # Normal pagination flow - show the requested page
            page_slice = self.get_page_slice(filtered_data, page_to_show)
            
            # Format product message
            message = self.format_product_message(page_slice, page_to_show, total_count, view_type)

            # Create product buttons
            product_buttons = self.create_product_buttons(page_slice, page_to_show)
            
            # Generate navigation buttons
            navigation_buttons = self.create_response_buttons(page_to_show, total_pages, total_count, view_type)
            
            # Combine all buttons
            all_buttons = product_buttons + navigation_buttons
            
            # Send a single message with all buttons
            dispatcher.utter_message(text=message, buttons=all_buttons)
            
            return [
                SlotSet("current_page", page_to_show),
                SlotSet("view_type", view_type),
                SlotSet("intent", "show_more"), 
                SlotSet("shopping_context", "product_browsing"),
                SlotSet("last_page", page_to_show)
            ]

        except Exception as e:
            print(f"Error in ActionShowMore: {str(e)}")
            dispatcher.utter_message(
                text="Unable to load products. Please choose an alternative:",
                buttons=[
                    {"title": "Show Bestsellers", "payload": "/show_bestsellers"},
                    {"title": "Show Discounted", "payload": "/show_discounted"},
                    {"title": "Show Regular", "payload": "/show_regular"},
                    {"title": "View Cart", "payload": "/view_cart"},
                    {"title": "Explore Products", "payload": "/reset_category_flow"}
                ]
            )
            return [
                SlotSet("current_page", 0),
                SlotSet("view_type", None),
                SlotSet("intent", None),
                SlotSet("shopping_context", None),
                SlotSet("last_page", None)
            ]

class ActionResetCategoryFlow(Action):
    def name(self) -> Text:
        return "action_reset_category_flow"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        # Show a confirmation message with a button to proceed
        dispatcher.utter_message(
            text="Are you sure you want to reset and explore categories again?",
            buttons=[
                {
                    "title": "Yes, Reset and Explore",
                    "payload": "/reset_category_flow"
                },
                {
                    "title": "View Cart",
                    "payload": "/view_cart"
                }
            ]
        )
        
        # Reset all relevant slots
        return [
            SlotSet("main_category", None),
            SlotSet("sub_category", None),
            SlotSet("current_page", 0),
            SlotSet("view_type", None),
            SlotSet("last_view_type", None),
            SlotSet("intent", "explore_products"),  # This ensures we stay in product exploration flow
            SlotSet("shopping_context", None),
            SlotSet("last_page", None)
        ]
    
class ActionAddToCart(Action):
    def name(self) -> Text:
        return "action_add_to_cart"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        try:
            # Extract product index from the entity
            product_idx_str = next(tracker.get_latest_entity_values("product_idx"), None)
            
            if not product_idx_str:
                dispatcher.utter_message(
                    text="Sorry, I couldn't understand which product you want to add. Please try again."
                )
                return []
            
            # Get current session products
            jewelry_action = JewelryAction()
            
            # Retrieve product details based on current view
            main_category = tracker.get_slot('main_category')
            sub_category = tracker.get_slot('sub_category')
            view_type = tracker.get_slot('view_type') or "regular"
            current_page = int(tracker.get_slot('current_page') or 0)
            
            # Debug information
            print(f"Adding to cart: product_idx={product_idx_str}, page={current_page}, view={view_type}")
            
            # Get the filtered data
            base_data = jewelry_action.get_base_filtered_data(main_category, sub_category)
            filtered_data = jewelry_action.apply_view_filter(base_data, view_type)
            
            # Convert product_idx to an integer
            try:
                product_idx = int(product_idx_str)
            except ValueError:
                print(f"Invalid product index: {product_idx_str}")
                dispatcher.utter_message(
                    text="Sorry, I couldn't identify the product you're trying to add. Please try again."
                )
                return []
                
            # Calculate the absolute index in the filtered data
            # The product_idx is 1-based (for user display), but we need 0-based for data access
            absolute_idx = product_idx - 1
            
            # Debug information
            print(f"Calculated absolute index: {absolute_idx}")
            
            # Make sure we have valid data and index is within range
            if filtered_data.empty or absolute_idx >= len(filtered_data) or absolute_idx < 0:
                print(f"Invalid index: absolute_idx={absolute_idx}, filtered_data size={len(filtered_data)}")
                dispatcher.utter_message(
                    text="Sorry, I couldn't find that product. Please try again."
                )
                return []
            
            # Get the product
            try:
                product = filtered_data.iloc[absolute_idx]
                
                # Safely get product details with appropriate conversions
                product_id = str(product.get('Product_ID', f"prod_{absolute_idx}"))  # Use absolute_idx instead of product_idx
                product_name = str(product['Product_Name'])
                
                # Safely convert base price to float
                try:
                    base_price = float(product['Base_Price_Without_Addon'])
                except (ValueError, TypeError):
                    # If conversion fails, use a default value
                    print(f"Warning: Could not convert base price to float: {product['Base_Price_Without_Addon']}")
                    base_price = 0.0
                
                # Handle discounted price with safe conversion
                discounted_price = None
                if 'Discounted_Base_Price_Without_Addon' in product:
                    discount_value = product['Discounted_Base_Price_Without_Addon']
                    # Check if discount is a valid number
                    if pd.notna(discount_value) and discount_value not in ['No Discount', 'NA', 'N/A', '-']:
                        try:
                            discounted_price = float(discount_value)
                        except (ValueError, TypeError):
                            print(f"Warning: Invalid discount value: {discount_value}")
                
                print(f"Found product: {product_name}, ID: {product_id}, Base Price: {base_price}, Discounted: {discounted_price}")
                
                # Get current cart
                cart = jewelry_action.get_cart(tracker)
                
                # Check if product is already in cart by comparing product_name instead of product_id
                product_in_cart = False
                for item in cart:
                    if item.get('product_name') == product_name:  # Compare by name instead of ID
                        item['quantity'] += 1
                        product_in_cart = True
                        break
                
                # If product not in cart, add it
                if not product_in_cart:
                    cart.append({
                        'product_id': product_id,
                        'product_name': product_name,
                        'base_price': base_price,
                        'discounted_price': discounted_price,
                        'quantity': 1
                    })
                
                # Store the last browsing state for "Continue Shopping"
                browsing_context = [
                    SlotSet("last_view_type", view_type),
                    SlotSet("last_page", current_page),
                    SlotSet("shopping_context", "product_browsing")
                ]
                
                # Send confirmation message with Continue Shopping option
                dispatcher.utter_message(
                    text=f"✅ Added {product_name} to your cart!",
                    buttons=[
                        {"title": "🛒 View Cart", "payload": "/view_cart"},
                        {"title": "🔄 Continue Shopping", "payload": "/continue_shopping"}
                    ]
                )
                
                # Update cart in slots and store context
                return [jewelry_action.set_cart(cart)] + browsing_context
                
            except Exception as e:
                print(f"Error getting product data: {str(e)}")
                raise
            
        except Exception as e:
            print(f"Error in ActionAddToCart: {str(e)}")
            dispatcher.utter_message(
                text="Sorry, I couldn't add this item to your cart. Please try again."
            )
            return []

class ActionViewCart(Action):
    def name(self) -> Text:
        return "action_view_cart"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        try:
            # Get current cart
            jewelry_action = JewelryAction()
            cart = jewelry_action.get_cart(tracker)
            
            if not cart:
                dispatcher.utter_message(
                    text="Your cart is empty. Would you like to explore products?",
                    buttons=[
                        {"title": "Explore Products", "payload": "/explore_products"},
                        {"title": "View Different Category", "payload": "/reset_category_flow"}
                    ]
                )
                return []
            
            # Calculate cart totals
            total_items = sum(item.get('quantity', 0) for item in cart)
            
            # Format cart message
            message = f"🛒 Your Cart ({total_items} items):\n\n"
            buttons = []
            
            total_original_price = 0
            total_final_price = 0
            
            for i, item in enumerate(cart, 1):
                # Extract product details
                product_name = item.get('product_name', 'Unknown Product')
                base_price = float(item.get('base_price', 0))
                discounted_price = float(item.get('discounted_price', 0)) if item.get('discounted_price') else None
                quantity = item.get('quantity', 1)
                product_id = item.get('product_id')
                
                # Calculate item totals
                item_base_total = base_price * quantity
                total_original_price += item_base_total
                
                # Calculate the actual price to charge (discounted or base)
                if discounted_price:
                    item_actual_total = discounted_price * quantity
                    price_display = f"₹{discounted_price} (₹{base_price} original)"
                    total_display = f"₹{item_actual_total:.2f}"
                    # Add to the final price
                    total_final_price += item_actual_total
                else:
                    item_actual_total = item_base_total
                    price_display = f"₹{base_price}"
                    total_display = f"₹{item_base_total:.2f}"
                    # Add to the final price
                    total_final_price += item_actual_total
                
                # Format item line
                message += f"{i}. {product_name}\n"
                message += f"   Price: {price_display} × {quantity} = {total_display}\n\n"
                
                # Add item control buttons
                buttons.extend([
                    {"title": f"➕ Add More {product_name}", "payload": f"/update_cart{{\"product_id\": \"{product_id}\", \"action\": \"increase\"}}"},
                    {"title": f"➖ Reduce {product_name}", "payload": f"/update_cart{{\"product_id\": \"{product_id}\", \"action\": \"decrease\"}}"},
                    {"title": f"❌ Remove {product_name}", "payload": f"/update_cart{{\"product_id\": \"{product_id}\", \"action\": \"remove\"}}"}
                ])
            
            # Add cart total section
            message += "📊 Cart Summary:\n"
            
            # Calculate savings
            savings = total_original_price - total_final_price
            savings_percentage = (savings / total_original_price * 100) if total_original_price > 0 else 0
            
            if savings > 0:
                message += f"Original Total: ₹{total_original_price:.2f}\n"
                message += f"Final Total: ₹{total_final_price:.2f}\n"
                message += f"Your Savings: ₹{savings:.2f} ({savings_percentage:.1f}%)\n"
            else:
                message += f"Total: ₹{total_final_price:.2f}\n"
            
            message += "Try Your Choice:/n https://sirpi-57.github.io/infinite-ai-jewelry-tryon/tryon.html"

            # Add navigation buttons
            navigation_buttons = [
                {"title": "🛍️ Continue Shopping", "payload": "/continue_shopping"},
                {"title": "🗑️ Clear Cart", "payload": "/clear_cart"},
                {"title": "💳 Checkout", "payload": "/checkout"}
            ]
            
            # Send message with cart details
            dispatcher.utter_message(text=message, buttons=navigation_buttons)
            
            # Store the shopping context
            return [SlotSet("shopping_context", "cart_viewing")]
            
        except Exception as e:
            print(f"Error in ActionViewCart: {str(e)}")
            dispatcher.utter_message(
                text="Sorry, I couldn't retrieve your cart information. Please try again."
            )
            return []


class ActionUpdateCart(Action):
    def name(self) -> Text:
        return "action_update_cart"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        try:
            # Extract update details from entities
            product_id = next(tracker.get_latest_entity_values("product_id"), None)
            update_action = next(tracker.get_latest_entity_values("action"), None)
            
            if not product_id or not update_action:
                dispatcher.utter_message(
                    text="Sorry, I couldn't update your cart. Please try again."
                )
                return []
            
            # Get current cart
            jewelry_action = JewelryAction()
            cart = jewelry_action.get_cart(tracker)
            updated_cart = []
            product_name = None
            
            # Process update based on action type
            for item in cart:
                if item.get('product_id') == product_id:
                    product_name = item.get('product_name', 'this item')
                    
                    if update_action == 'increase':
                        item['quantity'] += 1
                        updated_cart.append(item)
                    elif update_action == 'decrease':
                        item['quantity'] -= 1
                        if item['quantity'] > 0:
                            updated_cart.append(item)
                    elif update_action == 'remove':
                        # Don't add to updated cart to remove it
                        pass
                else:
                    updated_cart.append(item)
            
            # Prepare appropriate message
            if update_action == 'increase':
                message = f"✅ Added one more {product_name} to your cart."
            elif update_action == 'decrease' and product_name not in [item.get('product_name') for item in updated_cart]:
                message = f"❌ Removed {product_name} from your cart (quantity reached zero)."
            elif update_action == 'decrease':
                message = f"✅ Reduced quantity of {product_name} in your cart."
            elif update_action == 'remove':
                message = f"❌ Removed {product_name} from your cart."
            else:
                message = "✅ Cart updated successfully."
            
            dispatcher.utter_message(text=message)
            
            # Save updated cart
            cart_event = jewelry_action.set_cart(updated_cart)
            
            # Show the updated cart
            ActionViewCart().run(dispatcher, tracker, domain)
            
            return [cart_event, SlotSet("shopping_context", "cart_viewing")]
            
        except Exception as e:
            print(f"Error in ActionUpdateCart: {str(e)}")
            dispatcher.utter_message(
                text="Sorry, I couldn't update your cart. Please try again."
            )
            return []


class ActionClearCart(Action):
    def name(self) -> Text:
        return "action_clear_cart"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        jewelry_action = JewelryAction()
        
        buttons = [
            {"title": "🛍️ Continue Shopping", "payload": "/continue_shopping"},
            {"title": "🔍 Explore Categories", "payload": "/reset_category_flow"}
        ]
        
        dispatcher.utter_message(
            text="🗑️ Your cart has been cleared.",
            buttons=buttons
        )
        
        return [
            jewelry_action.set_cart([]),
            SlotSet("shopping_context", None)
        ]


class ActionContinueShopping(Action):
    def name(self) -> Text:
        return "action_continue_shopping"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        # Check if we have a detailed shopping context
        main_category = tracker.get_slot('main_category')
        sub_category = tracker.get_slot('sub_category')
        
        # Get the view type and page
        view_type = tracker.get_slot('last_view_type') or tracker.get_slot('view_type') or "regular"
        current_page = int(tracker.get_slot('current_page') or 0)
        
        print(f"Continue shopping context: view: {view_type}, page: {current_page}")
        
        if main_category and sub_category and view_type:
            # Tell the user we're returning to their previous browsing
            dispatcher.utter_message(text="Returning to where you left off...")
            
            # Directly handle showing the products based on the view type
            jewelry_action = JewelryAction()
            
            # Get base filtered data for the current category
            base_data = jewelry_action.get_base_filtered_data(main_category, sub_category)
            
            # Apply the appropriate filter based on view type
            if view_type == "bestseller":
                filtered_data = jewelry_action.apply_view_filter(base_data, "bestseller")
                display_type = "bestsellers"
            elif view_type == "discount":
                filtered_data = jewelry_action.apply_view_filter(base_data, "discount")
                display_type = "discounted products"
            else:  # regular
                filtered_data = base_data
                display_type = "products"
            
            # Calculate pagination
            total_count = len(filtered_data)
            total_pages = (total_count + jewelry_action.PRODUCTS_PER_PAGE - 1) // jewelry_action.PRODUCTS_PER_PAGE
            
            # Get the page to display (use current page, but ensure it's valid)
            page_to_show = min(current_page, total_pages - 1) if total_pages > 0 else 0
            
            # Get the slice of products for this page
            page_slice = jewelry_action.get_page_slice(filtered_data, page_to_show)
            
            if page_slice.empty:
                # No products on this page (could happen if products were removed)
                dispatcher.utter_message(
                    text=f"No {display_type} found on this page. Showing the first page instead."
                )
                page_to_show = 0
                page_slice = jewelry_action.get_page_slice(filtered_data, 0)
                
                # If still empty, show a message
                if page_slice.empty:
                    dispatcher.utter_message(
                        text=f"Sorry, we don't have any {display_type} in {main_category} {sub_category} at the moment."
                    )
                    return [SlotSet("view_type", view_type)]
            
            # Format the product message
            message = jewelry_action.format_product_message(page_slice, page_to_show, total_count, view_type)
            
            # Create product buttons
            product_buttons = jewelry_action.create_product_buttons(page_slice, page_to_show)
            
            # Generate navigation buttons
            navigation_buttons = jewelry_action.create_response_buttons(page_to_show, total_pages, total_count, view_type)
            
            # Combine all buttons
            all_buttons = product_buttons + navigation_buttons
            
            # Send the message with all buttons
            dispatcher.utter_message(text=message, buttons=all_buttons)
            
            # Set the appropriate slots
            return [
                SlotSet("current_page", page_to_show),
                SlotSet("view_type", view_type),
                SlotSet("intent", "show_products")
            ]
            
        elif main_category and sub_category:
            # We have category but not specific view, show view options
            message = f"Let's continue shopping in {main_category} {sub_category}."
            
            buttons = [
                {"title": "Show Bestsellers", "payload": f"/show_bestsellers{{\"main_category\": \"{main_category}\", \"sub_category\": \"{sub_category}\"}}"},
                {"title": "Show Discounted", "payload": f"/show_discounted{{\"main_category\": \"{main_category}\", \"sub_category\": \"{sub_category}\"}}"},
                {"title": "Show Regular", "payload": f"/show_regular{{\"main_category\": \"{main_category}\", \"sub_category\": \"{sub_category}\"}}"},
                {"title": "View Cart", "payload": "/view_cart"},
                {"title": "View Different Category", "payload": "/reset_category_flow"}
            ]
            
            dispatcher.utter_message(text=message, buttons=buttons)
            return [SlotSet("intent", "continue_shopping")]
        else:
            # No active category, go back to category selection
            return ActionResetCategoryFlow().run(dispatcher, tracker, domain)

class ActionCheckout(Action):
    def name(self) -> Text:
        return "action_checkout"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        jewelry_action = JewelryAction()
        cart = jewelry_action.get_cart(tracker)
        
        if not cart:
            dispatcher.utter_message(
                text="Your cart is empty. Please add some items before checkout.",
                buttons=[
                    {"title": "Explore Products", "payload": "/explore_products"},
                    {"title": "View Different Category", "payload": "/reset_category_flow"}
                ]
            )
            return []
        
        # Calculate total prices - using the same logic as in ActionViewCart
        total_original_price = 0
        total_final_price = 0
        
        for item in cart:
            # Extract product details
            base_price = float(item.get('base_price', 0))
            discounted_price = float(item.get('discounted_price', 0)) if item.get('discounted_price') else None
            quantity = item.get('quantity', 1)
            
            # Calculate item totals
            item_base_total = base_price * quantity
            total_original_price += item_base_total
            
            # Calculate the actual price to charge (discounted or base)
            if discounted_price:
                item_actual_total = discounted_price * quantity
                total_final_price += item_actual_total
            else:
                total_final_price += item_base_total
        
        # Create a simulated order ID
        import random
        order_id = f"ORD-{random.randint(100000, 999999)}"
        
        message = "🎉 Thank you for your order!\n\n"
        message += f"Order ID: {order_id}\n"
        message += f"Total Amount: ₹{total_final_price:.2f}\n\n"
        message += "This is a demonstration. In a real application, you would proceed to payment here.\n\n"
        message += "Your cart has been cleared. Would you like to continue shopping?"
        
        dispatcher.utter_message(
            text=message,
            buttons=[
                {"title": "Continue Shopping", "payload": "/reset_category_flow"},
                {"title": "Track Order", "payload": f"/track_order{{\"order_id\": \"{order_id}\"}}"}
            ]
        )
        
        # Clear the cart after checkout
        return [jewelry_action.set_cart([])]
    
class ActionInitiateOrderTracking(Action):
    def name(self) -> Text:
        return "action_initiate_order_tracking"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        # Reset order tracking state
        return [
            SlotSet("order_id", None),
            SlotSet("order_details", None),
            FollowupAction("utter_ask_order_id")
        ]


class ActionValidateOrderId(Action):
    def name(self) -> Text:
        return "action_validate_order_id"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        # Try to get order_id from entity first (from button payload)
        order_id = next(tracker.get_latest_entity_values("order_id"), None)
        
        print(f"DEBUG: Validating order ID. Entity value: {order_id}")
        print(f"DEBUG: Intent: {tracker.latest_message.get('intent', {}).get('name')}")
        print(f"DEBUG: Full message: {tracker.latest_message}")
        
        # If no entity, try to extract from text
        if not order_id:
            user_message = tracker.latest_message.get('text', '')
            print(f"DEBUG: No entity found, extracting from message: '{user_message}'")
            
            # Extract digits
            digits = ''.join(filter(str.isdigit, user_message))
            
            if not digits:
                dispatcher.utter_message(
                    text="Please select one of the sample order IDs, or enter a valid order number.",
                    buttons=[
                        {"title": "Track ORD-123456", "payload": "/provide_order_id{\"order_id\": \"ORD-123456\"}"},
                        {"title": "Track ORD-987654", "payload": "/provide_order_id{\"order_id\": \"ORD-987654\"}"},
                        {"title": "Back to Main Menu", "payload": "/greet"}
                    ]
                )
                return [FollowupAction("utter_ask_order_id")]
            
            order_id = f"ORD-{digits}"
        
        print(f"DEBUG: Final order_id: {order_id}")
        
        # For simplicity, accept any order ID as valid in this demonstration
        return [SlotSet("order_id", order_id)]


class ActionShowOrderStatus(Action):
    def name(self) -> Text:
        return "action_show_order_status"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
            
        order_id = tracker.get_slot('order_id')
        
        # Check if we have a valid order_id
        if not order_id:
            dispatcher.utter_message(
                text="I don't have a valid order ID to track. Let's try again.",
                buttons=[
                    {"title": "Track Order", "payload": "/track_order"},
                    {"title": "Back to Main Menu", "payload": "/greet"}
                ]
            )
            return [FollowupAction("utter_ask_order_id")]
        
        # Your existing code for generating order status...
        # Generate mock data for the demo
        import datetime
        import random
        
        # Generate random order data for demo purposes
        current_date = datetime.datetime.now()
        order_date = (current_date - datetime.timedelta(days=random.randint(3, 10))).strftime("%d %b %Y")
        
        # Status options with corresponding emojis and dates
        statuses = [
            {"status": "Order Placed", "emoji": "📝", "date": order_date, "completed": True},
            {"status": "Payment Confirmed", "emoji": "💰", "date": order_date, "completed": True},
            {"status": "Processing", "emoji": "⚙️", "date": (current_date - datetime.timedelta(days=random.randint(1, 3))).strftime("%d %b %Y"), "completed": True},
            {"status": "Ready for Shipment", "emoji": "📦", "date": (current_date - datetime.timedelta(days=random.randint(0, 2))).strftime("%d %b %Y"), "completed": True},
            {"status": "Shipped", "emoji": "🚚", "date": current_date.strftime("%d %b %Y"), "completed": True},
            {"status": "Out for Delivery", "emoji": "🛵", "date": (current_date + datetime.timedelta(days=1)).strftime("%d %b %Y"), "completed": False},
            {"status": "Delivered", "emoji": "✅", "date": (current_date + datetime.timedelta(days=2)).strftime("%d %b %Y"), "completed": False}
        ]
        
        # Determine current status (randomly between 3 and 5 for demo)
        current_status_idx = random.randint(3, 5)
        
        # Mark statuses as completed or pending based on current_status_idx
        for i in range(len(statuses)):
            statuses[i]["completed"] = i <= current_status_idx
        
        # Format the current status
        current_status = statuses[current_status_idx]["status"]
        
        # Create order details 
        product_types = ["Necklace", "Earrings", "Bracelet", "Ring", "Anklet"]
        product_name = f"{random.choice(['Gold', 'Silver', 'Diamond', 'Pearl'])} {random.choice(product_types)}"
        amount = random.randint(1500, 15000)
        shipping_address = "123 Sample Street, City, State, PIN"
        estimated_delivery = statuses[6]["date"]  # Use the delivery date from the statuses
        
        # Build status timeline message
        message = f"📋 *Order Details* (ID: {order_id})\n\n"
        message += f"*Product:* {product_name}\n"
        message += f"*Amount:* ₹{amount}\n"
        message += f"*Shipping Address:* {shipping_address}\n"
        message += f"*Current Status:* {current_status}\n"
        message += f"*Estimated Delivery:* {estimated_delivery}\n\n"
        
        # Create visual timeline
        message += "📊 *Order Timeline:*\n\n"
        
        for status in statuses:
            if status["completed"]:
                # Completed status
                message += f"{status['emoji']} {status['status']}: ✅ {status['date']}\n"
            else:
                # Pending status
                message += f"{status['emoji']} {status['status']}: ⏳ {status['date']} (Estimated)\n"
                
        # Store order details in a slot for future reference
        order_details = {
            "order_id": order_id,
            "product": product_name,
            "amount": amount,
            "shipping_address": shipping_address,
            "current_status": current_status,
            "estimated_delivery": estimated_delivery,
            "status_timeline": statuses
        }
        
        dispatcher.utter_message(
            text=message,
            buttons=[
                {"title": "View Order Details", "payload": "/view_order_details"},
                {"title": "Report an Issue", "payload": "/report_issue"},
                {"title": "Track Another Order", "payload": "/track_order"},
                {"title": "Back to Main Menu", "payload": "/greet"}
            ]
        )
        
        return [SlotSet("order_details", order_details)]


class ActionShowOrderDetails(Action):

    def name(self) -> Text:
        return "action_show_order_details"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        order_details = tracker.get_slot('order_details')
        
        if not order_details:
            dispatcher.utter_message(
                text="I don't have any order details to display. Please try tracking your order again.",
                buttons=[
                    {"title": "Track Order", "payload": "/track_order"},
                    {"title": "Back to Main Menu", "payload": "/greet"}
                ]
            )
            return []
        
        # Format all order details for display
        message = "📦 *Detailed Order Information*\n\n"
        message += f"*Order ID:* {order_details.get('order_id', 'N/A')}\n"
        message += f"*Product:* {order_details.get('product', 'N/A')}\n"
        message += f"*Amount:* ₹{order_details.get('amount', 'N/A')}\n"
        message += f"*Order Date:* {order_details.get('status_timeline', [])[0].get('date', 'N/A')}\n"
        message += f"*Current Status:* {order_details.get('current_status', 'N/A')}\n"
        message += f"*Shipping Address:* {order_details.get('shipping_address', 'N/A')}\n"
        message += f"*Estimated Delivery:* {order_details.get('estimated_delivery', 'N/A')}\n\n"
        
        # Add payment info
        message += "*Payment Information:*\n"
        message += "Method: Credit Card (ending in ****1234)\n"
        message += f"Amount: ₹{order_details.get('amount', 'N/A')}\n"
        message += "Status: Paid\n\n"
        
        # Add shipping info
        message += "*Shipping Information:*\n"
        message += "Courier: Express Delivery Services\n"
        message += "Tracking Number: EXP123456789\n\n"
        
        # Add a note about jewelry care
        message += "*Product Care:* All jewelry items come with a care instruction card. Please follow the instructions to maintain your item's appearance.\n"
        
        dispatcher.utter_message(
            text=message,
            buttons=[
                {"title": "Track Status", "payload": f"/track_order{{\"order_id\": \"{order_details.get('order_id', '')}\"}}"},
                {"title": "Report an Issue", "payload": "/report_issue"},
                {"title": "Track Another Order", "payload": "/track_order"},
                {"title": "Back to Main Menu", "payload": "/greet"}
            ]
        )
        
        return []


class ActionReportIssue(Action):
    def name(self) -> Text:
        return "action_report_issue"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        order_details = tracker.get_slot('order_details')
        order_id = order_details.get('order_id') if order_details else tracker.get_slot('order_id')
        
        if not order_id:
            dispatcher.utter_message(
                text="I need an order ID to report an issue. Please provide your order ID first.",
                buttons=[
                    {"title": "Track Order", "payload": "/track_order"}
                ]
            )
            return []
        
        # Generate a reference number for the issue
        import random
        import string
        
        reference_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        
        message = "🔔 *Issue Reported Successfully*\n\n"
        message += f"Thank you for bringing this to our attention. Your issue with order {order_id} has been logged.\n\n"
        message += f"*Reference Number:* {reference_id}\n\n"
        message += "Our customer service team will review your order and contact you within 24 hours.\n\n"
        message += "For immediate assistance, you can contact our customer support at:\n"
        message += "📞 +91-9994481257\n"
        message += "📧 support@infiniteai.in\n"
        
        dispatcher.utter_message(
            text=message,
            buttons=[
                {"title": "Track Order Status", "payload": f"/track_order{{\"order_id\": \"{order_id}\"}}"},
                {"title": "Track Another Order", "payload": "/track_order"},
                {"title": "Back to Main Menu", "payload": "/greet"}
            ]
        )
        
        return [SlotSet("issue_reference", reference_id)]
    



# Update this URL with your actual ngrok URL from Google Colab
CHATBOT_API_URL = "https://5884-34-16-172-151.ngrok-free.app"  # Replace with your actual ngrok URL
if CHATBOT_API_URL.endswith('/'):
    CHATBOT_API_URL = CHATBOT_API_URL[:-1]

class ActionJewelryStylingAdvice(Action):
    """Action to get jewelry styling advice from the external PDF chatbot service"""

    def name(self) -> Text:
        return "action_jewelry_styling_advice"

    def run(
        self, 
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:
        # Get the user's question from the latest message
        user_question = tracker.latest_message.get("text")
        
        # Show thinking message with rephrasing disabled
        dispatcher.utter_message(
            text="Let me look up some jewelry styling advice for you...",
            metadata={"from_jewelry_pdf": True, "rephrase": False}
        )
        
        try:
            # Call the PDF chatbot API
            response = requests.post(
                f"{CHATBOT_API_URL}/query",
                json={"question": user_question},
                timeout=300  # 5 minutes timeout
            )
            
            if response.status_code == 200:
                answer_data = response.json()
                styling_advice = answer_data.get("answer", "I couldn't find specific advice for that. Could you try asking differently?")
                
                # Send the response back to the user with rephrasing disabled
                dispatcher.utter_message(
                    text=styling_advice,
                    metadata={"from_jewelry_pdf": True, "rephrase": False}
                )
                return []
            else:
                error_msg = f"Error from styling service: {response.status_code} - {response.text}"
                print(error_msg)
                dispatcher.utter_message(
                    text="I'm having trouble connecting to my jewelry styling knowledge. Please try again later.",
                    metadata={"rephrase": False}  # Prevent LLM from rephrasing this response
                )
                return []
                
        except requests.exceptions.RequestException as e:
            # Handle connection errors
            print(f"Error connecting to PDF chatbot API: {str(e)}")
            dispatcher.utter_message(
                text="I'm having trouble connecting to my jewelry styling knowledge. Please try again later.",
                metadata={"from_jewelry_pdf": True, "rephrase": False}
            )
            return []
            
class ActionInitializeJewelryStyling(Action):
    """Action to initialize the jewelry styling service"""

    def name(self) -> Text:
        return "action_initialize_jewelry_styling"

    def run(
        self, 
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:
        try:
            # Check if the API is available
            response = requests.get(
                f"{CHATBOT_API_URL}/health",
                timeout=60
            )
            
            if response.status_code == 200:
                health_data = response.json()
                if health_data.get("ready", False):
                    # System is ready
                    return [SlotSet("jewelry_styling_initialized", True)]
                else:
                    # System is running but not ready
                    dispatcher.utter_message(
                        text="I'm still preparing my jewelry styling knowledge. Please try again in a moment.",
                        metadata={"from_jewelry_pdf": True, "rephrase": False}  # Prevent LLM from rephrasing this response
                    )
                    print("API is running but not ready yet")
                    return [SlotSet("jewelry_styling_initialized", False)]
            else:
                # Non-200 response
                dispatcher.utter_message(
                    text="I'm having trouble accessing my jewelry styling knowledge. Please try again later.",
                    metadata={"from_jewelry_pdf": True, "rephrase": False}  # Prevent LLM from rephrasing this response
                )
                print(f"API health check failed: {response.status_code} - {response.text}")
                return [SlotSet("jewelry_styling_initialized", False)]
                
        except requests.exceptions.RequestException as e:
            # Connection error
            dispatcher.utter_message(
                text="I'm having trouble connecting to my jewelry styling service. Please try again later.",
                metadata={"from_jewelry_pdf": True, "rephrase": False}  # Prevent LLM from rephrasing this response
            )
            print(f"Error connecting to PDF chatbot API: {str(e)}")
            return [SlotSet("jewelry_styling_initialized", False)]
        
class ActionAnalyzeReviewSentiment(Action):
    def name(self) -> Text:
        return "action_analyze_review_sentiment"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        # Get the review text
        review_text = tracker.latest_message.get('text', '')
        
        # Simple sentiment analysis using keyword matching
        # In a real system, you would use a more sophisticated NLP model
        positive_words = ['good', 'great', 'excellent', 'amazing', 'wonderful', 
                         'love', 'like', 'best', 'fantastic', 'helpful', 'happy',
                         'satisfied', 'perfect', 'awesome', 'impressive']
                         
        negative_words = ['bad', 'poor', 'terrible', 'awful', 'horrible', 
                         'hate', 'dislike', 'worst', 'disappointing', 'unhappy',
                         'unsatisfied', 'broken', 'useless', 'waste', 'expensive']
        
        # Count positive and negative words
        positive_count = sum(1 for word in positive_words if word in review_text.lower())
        negative_count = sum(1 for word in negative_words if word in review_text.lower())
        
        # Determine sentiment
        sentiment = "positive" if positive_count > negative_count else "negative"
        
        # Dispatch appropriate response based on sentiment
        if sentiment == "positive":
            dispatcher.utter_message(response="utter_thank_positive_review")
        else:
            dispatcher.utter_message(response="utter_thank_negative_review")
            
        # Ask if user wants to upload an image
        dispatcher.utter_message(response="utter_ask_for_image")
        
        # Store the review and sentiment
        return [
            SlotSet("review_text", review_text),
            SlotSet("review_sentiment", sentiment)
        ]

class ActionHandleReviewImage(Action):
    def name(self) -> Text:
        return "action_handle_review_image"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        # In Rasa, we can't directly handle file uploads through the chatbot
        # This would typically be done through a separate web interface
        # For demonstration, we'll just acknowledge the intent to upload
        
        dispatcher.utter_message(text="Thank you for wanting to share an image with your review! In a real application, this would open an upload dialog.")
        dispatcher.utter_message(response="utter_confirm_review_submission")
        
        return []