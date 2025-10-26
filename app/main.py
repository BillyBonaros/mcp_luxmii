import os
from fastmcp import FastMCP
import shopify
from dotenv import load_dotenv, find_dotenv
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware


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
    """Get order details by order id (e.g., '#12345')."""
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
def ping() -> str:
    """Simple ping test."""
    return "pong"

if __name__ == "__main__":
    # CRITICAL: Railway requires these exact settings
    port = int(os.environ.get("PORT", 8000))
    
    print(f"Starting FastMCP server on 0.0.0.0:{port}")
    
    try:
        mcp.run(
            transport="streamable-http", 
            port=port,
            host="0.0.0.0",  # MUST be 0.0.0.0 for Railway
            middleware=[cors_middleware]
        )
    except Exception as e:
        print(f"Server failed to start: {e}")
        raise
