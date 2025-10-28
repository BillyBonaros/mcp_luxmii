import os
from fastmcp import FastMCP
import shopify
from dotenv import load_dotenv, find_dotenv
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
import requests
from requests.exceptions import RequestException
from tools import *
from fastmcp.resources import TextResource

# Automatically finds .env in current directory or parent directories
load_dotenv(find_dotenv())
def init_shopify():
    try:
        shop_url = os.getenv("SHOP_URL")
        access_token = os.getenv("SHOPIFY_ACCESS_TOKEN")
        if not (shop_url and access_token):
            print("Warning: Missing Shopify credentials.")
            return False
        
        shop_url = f"https://{shop_url}/admin/api/2024-01"
        shopify.ShopifyResource.set_site(shop_url)
        shopify.ShopifyResource.set_headers({"X-Shopify-Access-Token": access_token})
        return True
    except Exception as e:
        print(f"Error initializing Shopify: {e}")
        return False

shopify_initialized = init_shopify()

cors_middleware = Middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=[
        "mcp-protocol-version",
        "mcp-session-id", 
        "Authorization",
        "Content-Type",
        "Accept",
        "X-Requested-With"
    ],
    expose_headers=["mcp-session-id"],
    allow_credentials=False,
)

mcp = FastMCP("shopify-mcp")

@mcp.tool()
def get_order_details_by_order_id(order_id: str):
    """Get order details by order id (order name) (e.g., '#12345')."""
    try:
        oid = str(order_id)
        if not oid.startswith("#"):
            oid = f"#{oid}"
        order = shopify.Order.find_first(name=oid, status="any")
        if order:
            return order.to_dict()
        return {"error": "couldn't fetch order details"}
    except Exception as e:
        return {"error": str(e)}



@mcp.tool()
def search_orders_by_email(email:str):
    """Get the details of all orders of a customer using their email."""

    max_retries=3
    url = f"https://luxmii.com/admin/api/2024-10/orders.json?status=any&email={email}"
    headers = {
        'Content-Type': 'application/json',
        'X-Shopify-Access-Token': os.getenv("SHOPIFY_ACCESS_TOKEN")
    }
    retries = 0
    while retries <= max_retries:
        try:
            response = requests.get(url, headers=headers, verify=False)
            response.raise_for_status()
            return response.json().get("orders", [])
        except RequestException as e:
            retries += 1
            if retries > max_retries:
                raise Exception(f"Failed to search orders: {str(e)}")
            time.sleep(2 ** retries)










@mcp.tool()
def get_order_eligibility(order_id):
    """
    MCP Tool Function: Get return eligibility for all items in an order
    You can get the order ID from the shopify data. Except if its provided by the user.
    Its not the order name like #12345. It can reach up to 20 characters.
    Args:
        order_id (str): The Shopify order ID
        
    Returns:
        dict: Contains order info and eligibility details for each item
    """
    try:
        # Get all required data
        order_data = get_shopify_data(order_id)
        status_map = get_item_status(order_id)
        customer_id = order_data['customer']['id']
        order_count = get_order_count(customer_id)
        
        # Extract order info
        order_info = {
            "order_id": order_id,
            "order_name": order_data['name'],
            "customer_email": order_data['email'],
            "customer_name": order_data['billing_address']['name'],
            "order_count": order_count,
            "total_amount": f"{order_data['total_price_set']['presentment_money']['amount']} {order_data['total_price_set']['presentment_money']['currency_code']}",
            "discount_codes": [d['code'] for d in order_data.get("discount_codes", [])]
        }
        
        # Process each item
        items_eligibility = []
        fulfillments = order_data.get("fulfillments", [])
        refunds = order_data.get("refunds", [])
        
        for item in order_data['line_items']:
            if item['current_quantity'] > 0:  # Only process items that haven't been fully refunded
                
                item_id = item['id']
                quantity = item['quantity']
                price_per_item = float(item['price'])
                
                # Calculate discount information
                discount_allocs = item.get("discount_allocations", [])
                total_discount_amount = sum(float(d['amount']) for d in discount_allocs)
                
                discount_percentage = 0
                if quantity > 0 and total_discount_amount > 0:
                    original_item_price = price_per_item / quantity
                    discount_percentage = round((total_discount_amount / quantity / original_item_price) * 100, 2)
                
                # Check delivery status
                delivered_at = None
                for f in fulfillments:
                    for f_item in f.get("line_items", []):
                        if f_item['id'] == item_id and f.get("shipment_status") == "delivered":
                            delivered_at = f.get("updated_at")
                
                days_held = get_days_held(delivered_at)
                
                # Check various flags
                is_final_sale = any(p['value'] == "Final Sale" for p in item.get("properties", []))
                has_discount = bool(order_data.get("discount_codes"))
                
                # Check if item was returned
                was_returned = any(
                    item_id == refund_line_item.get("line_item_id")
                    for refund in refunds
                    for refund_line_item in refund.get("refund_line_items", [])
                )
                
                # Get eligibility
                eligibility_status, return_options = get_eligibility(
                    is_final_sale, days_held, discount_percentage, has_discount, order_count
                )
                
                # Check for variant discount
                variant_id = item.get("variant_id")
                variant_price, compare_at_price = get_variant_prices(variant_id)
                has_variant_discount = compare_at_price is not None and variant_price is not None and compare_at_price > variant_price
                
                # Calculate line totals
                pm = item["price_set"]["presentment_money"]
                amount = pm["amount"]
                currency = pm["currency_code"]
                line_discount = sum([float(i['amount_set']['presentment_money']['amount']) for i in item['discount_allocations']])
                line_gross = (amount * quantity)
                line_net = (float(line_gross) - float(line_discount))
                
                item_eligibility = {
                    "item_name": item["name"],
                    "sku": item["sku"],
                    "line_item_id": item['id'],
                    "quantity": quantity,
                    "line_net_amount": f"{line_net} {currency}",
                    "discount_percentage": discount_percentage,
                    "has_variant_discount": has_variant_discount,
                    "days_held": days_held,
                    "fulfillment_status": status_map.get(item_id, "Unknown"),
                    "was_returned": was_returned,
                    "is_final_sale": is_final_sale,
                    "eligibility_status": eligibility_status,
                    "return_options": return_options
                }
                
                items_eligibility.append(item_eligibility)
        
        return {
            "success": True,
            "order_info": order_info,
            "items": items_eligibility
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "order_id": order_id
        }



# Add the guidelines as a resource
guidelines_resource = TextResource(
    uri="guidelines://email-response",
    name="Email Response Guidelines",
    text=EMAIL_GUIDELINES,
    description="Comprehensive guidelines for writing customer email responses",
    tags={"guidelines", "email", "customer-service"}
)

mcp.add_resource(guidelines_resource)














if __name__ == "__main__":
    print("=== FastMCP Server Starting ===")
    
    # Check environment
    port = int(os.environ.get("PORT", 8000))
    print(f"PORT from environment: {port}")
    print(f"SHOP_URL: {os.getenv('SHOP_URL')}")
    
    try:
        print("Initializing Shopify...")
        shopify_initialized = init_shopify()
        print(f"Shopify initialized: {shopify_initialized}")
        
        print(f"Starting server on 0.0.0.0:{port}")
        mcp.run(
            transport="streamable-http", 
            port=port,
            host="0.0.0.0",
            middleware=[cors_middleware]
        )
    except Exception as e:
        print(f"FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        raise

