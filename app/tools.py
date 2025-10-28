import os
import requests
import time
from datetime import datetime, timezone
from dotenv import load_dotenv
from requests.exceptions import RequestException
import urllib3

# Disable SSL warnings and load environment
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
load_dotenv()
API_KEY = os.getenv("SHOPIFY_ACCESS_TOKEN")

# Shopify API Headers
HEADERS = {
    'Content-Type': 'application/json',
    'X-Shopify-Access-Token': API_KEY
}

def get_shopify_data(order_id, max_retries=3):
    """Get order data from Shopify API"""
    url = f"https://luxmii.com/admin/api/2024-10/orders/{order_id}.json"
    for attempt in range(max_retries + 1):
        try:
            response = requests.get(url, headers=HEADERS, verify=False)
            response.raise_for_status()
            return response.json()["order"]
        except RequestException:
            if attempt == max_retries:
                raise
            time.sleep(2 ** attempt)

def get_item_status(order_id, max_retries=3):
    """Get fulfillment status for order items"""
    url = f"https://luxmii.com/admin/api/2024-04/orders/{order_id}/fulfillment_orders.json"
    for attempt in range(max_retries + 1):
        try:
            response = requests.get(url, headers=HEADERS, verify=False)
            response.raise_for_status()
            fulfillment_orders = response.json()["fulfillment_orders"]
            status_map = {}
            for fo in fulfillment_orders:
                for item in fo["line_items"]:
                    status_map[item["line_item_id"]] = fo["status"]
            return status_map
        except RequestException:
            if attempt == max_retries:
                raise
            time.sleep(2 ** attempt)

def get_order_count(customer_id):
    """Get customer's total order count"""
    url = f"https://luxmii.com/admin/api/2024-04/customers/{customer_id}.json"
    response = requests.get(url, headers=HEADERS, verify=False)
    response.raise_for_status()
    return response.json()['customer']['orders_count']

def get_variant_prices(variant_id):
    """Get variant pricing information"""
    url = f"https://luxmii.com/admin/api/2024-04/variants/{variant_id}.json"
    try:
        response = requests.get(url, headers=HEADERS, verify=False)
        response.raise_for_status()
        variant = response.json()["variant"]
        price = float(variant.get("price", 0))
        compare_at_price = float(variant["compare_at_price"]) if variant.get("compare_at_price") else 0
        return price, compare_at_price
    except Exception as e:
        print(f"Error fetching variant {variant_id}: {e}")
        return None, None

def get_days_held(delivered_at):
    """Calculate days since delivery"""
    if not delivered_at:
        return None
    delivered_dt = datetime.fromisoformat(delivered_at)
    now = datetime.now(timezone.utc).astimezone(delivered_dt.tzinfo)
    return (now - delivered_dt).days

def get_eligibility(is_final_sale, days_held, discount_pct, has_discount, order_count):
    """Determine return eligibility and options"""
    if is_final_sale:
        return "FINAL SALE", ["Cannot be returned"]
    if days_held is not None and days_held > 30:
        return "EXPIRED", ["Store credit (-$20 USD label)"]
    if discount_pct > 20:
        return "More than 20% off", ["Store credit (-$20 USD label)",
                                      "Item exchange (-$20 USD label)",
                                      "Alteration subsidy: 10% refund + $20 USD gift voucher"]
    if order_count == 1:
        return "ELIGIBLE", [
            "120% store credit + free returns",
            "Item exchange (-$20 USD label)",
            "Refund (-$30 USD label)",
            "Alteration subsidy: 10% refund + $20 USD gift voucher"
        ]
    elif has_discount:
        return "ELIGIBLE", [
            "Store credit (-$20 USD label)",
            "Item exchange (-$20 USD label)",
            "Alteration subsidy: 10% refund + $20 USD gift voucher",
            "Discretionary Refunds: We reserve the right to approve a refund outside of our standard policy if, in our judgment, it is appropriate to do so."
        ]
    else:
        return "ELIGIBLE", [
            "120% store credit + free returns",
            "Item exchange (-$20 USD label)",
            "Refund (-$30 USD label)",
            "Alteration subsidy: 10% refund + $20 USD gift voucher"
        ]

# def get_order_eligibility(order_id):
#     """
#     MCP Tool Function: Get return eligibility for all items in an order
    
#     Args:
#         order_id (str): The Shopify order ID
        
#     Returns:
#         dict: Contains order info and eligibility details for each item
#     """
#     try:
#         # Get all required data
#         order_data = get_shopify_data(order_id)
#         status_map = get_item_status(order_id)
#         customer_id = order_data['customer']['id']
#         order_count = get_order_count(customer_id)
        
#         # Extract order info
#         order_info = {
#             "order_id": order_id,
#             "order_name": order_data['name'],
#             "customer_email": order_data['email'],
#             "customer_name": order_data['billing_address']['name'],
#             "order_count": order_count,
#             "total_amount": f"{order_data['total_price_set']['presentment_money']['amount']} {order_data['total_price_set']['presentment_money']['currency_code']}",
#             "discount_codes": [d['code'] for d in order_data.get("discount_codes", [])]
#         }
        
#         # Process each item
#         items_eligibility = []
#         fulfillments = order_data.get("fulfillments", [])
#         refunds = order_data.get("refunds", [])
        
#         for item in order_data['line_items']:
#             if item['current_quantity'] > 0:  # Only process items that haven't been fully refunded
                
#                 item_id = item['id']
#                 quantity = item['quantity']
#                 price_per_item = float(item['price'])
                
#                 # Calculate discount information
#                 discount_allocs = item.get("discount_allocations", [])
#                 total_discount_amount = sum(float(d['amount']) for d in discount_allocs)
                
#                 discount_percentage = 0
#                 if quantity > 0 and total_discount_amount > 0:
#                     original_item_price = price_per_item / quantity
#                     discount_percentage = round((total_discount_amount / quantity / original_item_price) * 100, 2)
                
#                 # Check delivery status
#                 delivered_at = None
#                 for f in fulfillments:
#                     for f_item in f.get("line_items", []):
#                         if f_item['id'] == item_id and f.get("shipment_status") == "delivered":
#                             delivered_at = f.get("updated_at")
                
#                 days_held = get_days_held(delivered_at)
                
#                 # Check various flags
#                 is_final_sale = any(p['value'] == "Final Sale" for p in item.get("properties", []))
#                 has_discount = bool(order_data.get("discount_codes"))
                
#                 # Check if item was returned
#                 was_returned = any(
#                     item_id == refund_line_item.get("line_item_id")
#                     for refund in refunds
#                     for refund_line_item in refund.get("refund_line_items", [])
#                 )
                
#                 # Get eligibility
#                 eligibility_status, return_options = get_eligibility(
#                     is_final_sale, days_held, discount_percentage, has_discount, order_count
#                 )
                
#                 # Check for variant discount
#                 variant_id = item.get("variant_id")
#                 variant_price, compare_at_price = get_variant_prices(variant_id)
#                 has_variant_discount = compare_at_price is not None and variant_price is not None and compare_at_price > variant_price
                
#                 # Calculate line totals
#                 pm = item["price_set"]["presentment_money"]
#                 amount = pm["amount"]
#                 currency = pm["currency_code"]
#                 line_discount = sum([float(i['amount_set']['presentment_money']['amount']) for i in item['discount_allocations']])
#                 line_gross = (amount * quantity)
#                 line_net = (float(line_gross) - float(line_discount))
                
#                 item_eligibility = {
#                     "item_name": item["name"],
#                     "sku": item["sku"],
#                     "line_item_id": item['id'],
#                     "quantity": quantity,
#                     "line_net_amount": f"{line_net} {currency}",
#                     "discount_percentage": discount_percentage,
#                     "has_variant_discount": has_variant_discount,
#                     "days_held": days_held,
#                     "fulfillment_status": status_map.get(item_id, "Unknown"),
#                     "was_returned": was_returned,
#                     "is_final_sale": is_final_sale,
#                     "eligibility_status": eligibility_status,
#                     "return_options": return_options
#                 }
                
#                 items_eligibility.append(item_eligibility)
        
#         return {
#             "success": True,
#             "order_info": order_info,
#             "items": items_eligibility
#         }
        
#     except Exception as e:
#         return {
#             "success": False,
#             "error": str(e),
#             "order_id": order_id
#         }

# # Example usage for MCP tool
# def format_eligibility_response(order_id):
#     """
#     Formatted response for MCP tool - returns human-readable eligibility text
#     """
#     result = get_order_eligibility(order_id)
    
#     if not result["success"]:
#         return f"Error processing order {order_id}: {result['error']}"
    
#     order_info = result["order_info"]
#     items = result["items"]
    
#     response = f"""ORDER ELIGIBILITY REPORT
    
# Order: {order_info['order_name']}
# Customer: {order_info['customer_name']} ({order_info['customer_email']})
# Customer Status: {"First-time customer" if order_info['order_count'] == 1 else f"Returning customer - {order_info['order_count']} orders"}
# Total: {order_info['total_amount']}
# Discount Codes: {', '.join(order_info['discount_codes']) if order_info['discount_codes'] else 'None'}

# ITEM ELIGIBILITY:
# """
    
#     for i, item in enumerate(items, 1):
#         response += f"\n{i}. {item['item_name']} (SKU: {item['sku']})\n"
#         response += f"   Quantity: {item['quantity']}\n"
#         response += f"   Net Amount: {item['line_net_amount']}\n"
#         response += f"   Status: {item['eligibility_status']}\n"
        
#         if item['has_variant_discount']:
#             response += f"   ⚠️  VARIANT DISCOUNT DETECTED - MANUAL REVIEW REQUIRED\n"
        
#         if item['days_held']:
#             response += f"   Days Held: {item['days_held']}\n"
        
#         if item['was_returned']:
#             response += f"   Status: ALREADY RETURNED\n"
        
#         response += f"   Return Options:\n"
#         for option in item['return_options']:
#             response += f"   • {option}\n"
    
#     return response
