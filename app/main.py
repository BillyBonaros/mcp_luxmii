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
    Retrieves the return eligibility status for every item in a specific Shopify order.
    You can obtain the Shopify Order ID (a unique 10–20 character identifier, not the order name like #12345) using the companion tool get_order_details_by_order_id, which accepts the order name as input.
    Alternatively, the Order ID may be provided directly by the user
    
    Arguments:
    order_id (str) – The Shopify Order ID used to identify the order.

    Returns:
    dict – A structured response containing:

    General order information (order ID, customer details, total amount, etc.)
    Eligibility details for each item in the order, including:
    Return status (eligible/ineligible)
    Available return options (store credit, refund, exchange, etc.)
    Any applicable conditions or restrictions
    """
    try:
        # Get all required data
        order_data = get_shopify_data(order_id)
        status_map = get_item_status(order_id)
        customer_id = order_data['customer']['id']
        order_count = get_order_count(customer_id)
        results = process_order_items(order=order_data, statuses=status_map, order_count=order_count)
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

        return {
            "success": True,
            "order_info": order_info,
            "items": results
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "order_id": order_id
        }



# # Add the guidelines as a resource
# guidelines_resource = TextResource(
#     uri="guidelines://email-response",
#     name="Email Response Guidelines",
#     text=EMAIL_GUIDELINES,
#     description="Comprehensive guidelines for writing customer email responses",
#     tags={"guidelines", "email", "customer-service"}
# )

# mcp.add_resource(guidelines_resource)




@mcp.tool()
def get_email_response_guidelines():
    """
    Use this tool to provide you email response guidelines. eg how to write email responses for our braand
    
    """

    return(EMAIL_GUIDELINES)







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

