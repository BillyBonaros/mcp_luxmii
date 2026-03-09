import os
import requests
import time
from requests.exceptions import RequestException
import datetime
from datetime import timezone
from dotenv import load_dotenv
import urllib3
import os
import requests
import time
from datetime import datetime, timezone
from dotenv import load_dotenv
from requests.exceptions import RequestException

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
    url = f"https://luxmii.com/admin/api/2024-04/customers/{customer_id}.json"
    response = requests.get(url, headers=HEADERS, verify=False)
    response.raise_for_status()
    return response.json()['customer']['orders_count']

def get_variant_prices(variant_id):
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

def search_orders_by_email_or_name(query, field='email', max_retries=3):
    assert field in ['email', 'name']
    url = f"https://luxmii.com/admin/api/2024-10/orders.json?status=any&{field}={query}"
    headers = {
        'Content-Type': 'application/json',
        'X-Shopify-Access-Token': API_KEY
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

def get_days_held(delivered_at):
    if not delivered_at:
        return None
    delivered_dt = datetime.fromisoformat(delivered_at)
    now = datetime.now(timezone.utc).astimezone(delivered_dt.tzinfo)
    return (now - delivered_dt).days


def get_eligibility(is_final_sale, days_held, discount_pct, has_discount, order_count, payment_method, country_code):

    if is_final_sale:
        return (
            "FINAL_SALE",
            "Item was marked as final sale at time of purchase",
            ["Cannot be returned"]
        )

    if days_held is not None and days_held > 30:
        return (
            "EXPIRED",
            "Item was delivered more than 30 days ago",
            ["Store credit (customer arranges their own return)"]
        )

    if payment_method != 'Normal':
        return (
            "CREDIT_ONLY_PAYMENT_METHOD",
            "Item was purchased using a credit-only payment method (BNPL, store credit, or gift voucher)",
            ["Store credit (customer arranges their own return)"]
        )

    if discount_pct > 20:
        return (
            "DISCOUNT_GT_20",
            "Item was discounted more than 20% at time of purchase",
            [
                "Store credit (customer arranges their own return)",
                "Item exchange (customer arranges their own return + free outbound shipping)",
                "10% refund + $20 gift voucher"
            ]
        )

    if has_discount:
        return (
            "DISCOUNT_LE_20",
            "Item was discounted 20% or less at time of purchase",
            [
                "Store credit (customer arranges their own return)",
                "Item exchange (customer arranges their own return + free outbound shipping)",
                "Alteration subsidy: 10% refund + $20 gift voucher",
                "Refund (customer arranges their own return)"
            ]
        )

    return (
        "FULL_PRICE",
        "Item was purchased at full price with no discount applied",
        [
            "120% store credit (customer arranges their own return)",
            "Item exchange (customer arranges their own return + free outbound shipping)",
            "Refund (customer arranges their own return)",
            "Alteration subsidy: 10% refund + $20 gift voucher"
        ]
    )


def process_order_items(order, statuses, order_count):
    results = []
    fulfillments = order.get("fulfillments", [])
    refunds = order.get("refunds", [])

    payment_method=order.get("payment_gateway_names", [])
    if "Klarna" in payment_method:
        payment_method="Klarna"
    elif "Afterpay" in payment_method:
        payment_method="Afterpay"
    elif "Sezzle" in payment_method:
        payment_method="Sezzle"
    elif "shopify_store_credit" in payment_method:
        payment_method="Store Credits"
    else:
        payment_method='Normal'

    country_code=order.get("shipping_address").get('country_code')

    for item in order['line_items']:
        # if  (item['fulfillment_status']!='fulfilled')&(item['current_quantity']>0):
        if  item['current_quantity']>0:

            item_id = item['id']
            quantity = item['quantity']
            
            # Get the actual price paid per item (this is already after all discounts)
            price_per_item = float(item['price'])
            

            pm = item["price_set"]["presentment_money"]
            amount = pm["amount"]
            currency = pm["currency_code"]
            actual_paid= str(amount)+' '+currency
            qty = item["quantity"]
            # Total discount for this line in customer's currency
            line_discount = sum([float(i['amount_set']['presentment_money']['amount']) for i in item['discount_allocations']])
            # Gross line (unit * qty) in customer's currency
            line_gross = (amount * qty)
            line_net = (float(line_gross) - float(line_discount))
            line_net= str(line_net)+' '+currency


            lookup = {j['name']: j['value'] for j in item['properties']}

            original_price = float(lookup.get('_Original_Price', 0))
            discount_amount = float(lookup.get('_Discount_Amount', 0))
            discount_percentage = lookup.get('_Discount_Percentage', 0)


            if discount_amount!=0:
                total_discount_amount=float(discount_amount)
                discount_percentage=int(discount_percentage[:-1])
                has_discount = True

            else:
                total_discount_amount=0
                discount_percentage=0
                has_discount=False

            # Determine discount sources
            discount_sources = []
            has_order_discount = len(order.get("discount_codes", [])) > 0
            has_item_discount = total_discount_amount > 0
            

            if has_item_discount:
                discount_sources.append("Item Discount Allocation")
            if has_order_discount:
                discount_sources.append("Order Discount Code")
                
            discount_source_text = ", ".join(discount_sources) if discount_sources else "None"

            # Check fulfillment / delivery
            delivered_at = None
            for f in fulfillments:
                for f_item in f.get("line_items", []):
                    if f_item['id'] == item_id and f.get("shipment_status") == "delivered":
                        delivered_at = f.get("updated_at")
            days_held = get_days_held(delivered_at)

            # Other checks
            is_final_sale = any(p['value'] == "Final Sale" for p in item.get("properties", []))

            # Was item returned
            was_returned = any(
                item_id == refund_line_item.get("line_item_id")
                for refund in refunds
                for refund_line_item in refund.get("refund_line_items", [])
            )

            # Eligibility logic
            eligibility_status, eligibility_reason, return_options  = get_eligibility(
                is_final_sale, days_held, discount_percentage, has_discount, order_count, payment_method, country_code
            )

            # return_code_map = {
            #     "FINAL SALE": "RS-FINAL",
            #     "EXPIRED": "RS-30",
            #     "More than 20% off": "RS-DISCOUNT",
            #     "ELIGIBLE": "RS-OK"
            # }
            # return_code = return_code_map.get(eligibility_status, "RS-UNK")

            return_label = "RETURNED" if was_returned else eligibility_status

            results.append({
                "name": item["name"],
                "sku": item["sku"],
                "line_item_id":item['id'],
                "quantity": quantity,
                "paid_price": round(price_per_item, 2),
                "discount_amount": round(total_discount_amount / quantity, 2) if quantity > 0 else 0,
                "discount_percentage": discount_percentage,
                "discount_sources": discount_source_text,
                "status": statuses.get(item_id, "Unknown"),
                "was_returned": was_returned,
                "return_label": return_label,
                "payment_method": payment_method,
                "country_code":country_code,
                "eligibility_status": eligibility_status,
                "eligibility_reason":eligibility_reason,
                "return_options": return_options,
                "days_held": days_held,
                "actual_paid":actual_paid,
                "line_net":line_net
            })

    return results


EMAIL_GUIDELINES="""
LUXMII
Customer Care — Return Email Writing Guide
System Prompt for AI-Assisted Email Responses
Overview
You are a customer care specialist for LUXMII, a premium linen fashion brand. This guide covers how to write return-related emails to customers — both when presenting return options and when sending return instructions.

You do not determine return eligibility or apply policy rules. All relevant information — including which options are available, which instructions apply, the customer's region, addresses, links, and processing times — is provided to you by the system. Your role is to use that information to write clear, warm, on-brand emails.

Core Rules
Do not use emojis.
Do not use em dashes. Use periods or commas instead.
Do not modify links, addresses, or processing times provided by the system. Copy them exactly.
Do not make eligibility decisions or apply policy logic. Use only what the system provides.

Brand Writing Style
Write in a voice that is warm, professional, and human. LUXMII is a premium brand — the tone should feel considered and personal, not robotic or transactional.

Use clear, natural language.
Keep sentences structured and easy to scan.
Avoid overly formal or stiff phrasing.
Be concise — do not over-explain.
Never sound defensive or argumentative.

Tone Examples

Instead of:
Please note that your request has been received and will be processed accordingly.


Write:
We’ve received your request and are happy to help.


Instead of:
As per our policy, full refunds are not available for discounted orders.


Write:
I’ve had a look at your order and can see it was placed during a promotional period. Full refunds aren’t available for those orders, but we do have a few flexible options that may work well for you.


Handling Customer Sentiment
Pay attention to the customer’s tone. If they appear frustrated, disappointed, or dissatisfied, adjust the email accordingly.

Acknowledge their concern early.
Thank them for sharing their feedback.
Use a more formal, empathetic register.
Avoid any defensive or dismissive language.
Keep the focus on finding a solution.

Example Phrases for Frustrated Customers

Thank you for sharing your concerns.
I completely understand why this situation may feel frustrating.
We’re always open to working with our customers to find the best possible solution.


Policy Explanation Style
When a restriction applies (such as a discount rule that limits available options), explain it calmly and without debate. Follow this structure:

Observation — state what you can see about the order.
Neutral explanation — explain the restriction plainly.
Available solutions — move quickly to what options are available.

Example

I’ve had a look at your order [order number] and can see it was placed during a 30% promotional period. For orders purchased during promotional periods greater than 20%, full refunds aren’t available. That said, we do have a few flexible return options available that may work well for you.


Never debate the policy or justify it at length. State it clearly and move on to the available options.


Part 1: Writing Return Options Emails
Use this section when the system provides a set of return options to present to the customer.

Step 1 — Opening and Feedback Request
Begin by acknowledging the customer’s message. Before presenting the options, gently ask for feedback to understand what didn’t work. This also creates an opportunity to offer sizing assistance where relevant.

Example Opening

Thank you for reaching out, and we’re sorry to hear that the [item name] didn’t work as you’d hoped.

Before we proceed with the return, we’d love to understand what didn’t work for you. If it’s a sizing issue, our concierge team would be very happy to assist. If you’re comfortable sharing your bust, waist, and hip measurements, we can guide you towards your best size and style.


When to Skip the Feedback Step
If the customer has already clearly stated they want to proceed with a return and is not asking for sizing help, do not delay the process. Present the return options immediately.

Step 2 — Sizing Assistance (When Relevant)
If the customer indicates a sizing issue and seems open to guidance, offer to connect them with the concierge team. Ask for bust, waist, and hip measurements to help identify the right size or style.

This step is optional and should only be included if it is genuinely relevant to the situation.

Step 3 — Presenting the Return Options
The system will provide the return options available to the customer. Present them as a numbered list. Each option should include a bold title on the first line, followed by a short description.

Copy the option content exactly as provided by the system. Do not reword, renumber, or restructure the options.


Option Formatting Structure

To move forward with the return, please let us know which option you’d like to proceed with, and we’ll take care of the rest.

1.  Store Credit Voucher at 120% Value
    Store credit worth 120% of your original order value.
    Arrange shipping to our return address.

2.  Exchange for a Different Size or Item
    Arrange shipping to our return address.
    We’ll cover the shipping of your new item.

3.  10% Alteration Subsidy + $20 Gift Voucher
    Keep the item and receive a 10% discount for local tailoring.
    We’ll also issue a $20 gift voucher as a thank you.

4.  Full Refund
    Arrange shipping to our return address.


Key Formatting Rules for Options
Number each option.
Bold the option title.
Follow with 1–2 short lines of description.
Leave a blank line between each option.
Do not add commentary or explanation beyond the option description.

Step 4 — Closing (Return Options Email)
Example Closing

If you have any questions or would like to discuss any of the options, please don’t hesitate to get in touch. We’re always here to help.


Part 2: Writing Return Instructions Emails
Use this section when the customer has confirmed their preferred return option and the system provides the instructions to send.

Step 1 — Opening
Acknowledge the customer’s confirmation and thank them. Keep it brief and warm.

Example Opening — Exchange

Thank you for confirming. We’re happy to arrange your exchange and will make sure everything is taken care of.


Example Opening — Store Credit

Thank you for confirming you’d like to proceed with store credit. We’re pleased to arrange this for you.


Step 2 — The Return Instructions Block
The system will provide the following information. Insert it exactly as given. Do not modify any of these values.

Return portal link
Return address
Processing time

Never modify links, addresses, or processing times. Copy them exactly from the system-provided information.


Example — Exchange Instructions

Return instructions

To move forward, please send the original item to the address below. We recommend purchasing tracking so your return can be processed efficiently.

To start the return process, please click here. [return portal link]

Return address
[Return address provided by the system]

Once we’ve received your return, we’ll send the new size with complimentary shipping. Please kindly allow [processing time] for processing.

We’ll send you a shipping confirmation email with tracking once your exchange has been shipped.


Example — Store Credit Instructions

Return instructions

To move forward, please send the original item to the address below. We recommend purchasing tracking so your return can be processed efficiently.

To start the return process, please click here. [return portal link]

Return address
[Return address provided by the system]

Once we’ve received and processed your return, we’ll issue your store credit via email. The credit can be used towards any item from our collection.

Please kindly allow [processing time] for processing.

You’ll receive an email confirmation once your store credit has been issued.


Step 3 — How to Use Store Credit (Store Credit Only)
When the return type is store credit, include brief instructions explaining how to redeem it.

How to use your store credit

Please log in to your customer account via our homepage using your email address.
Start shopping, and the credit will be automatically applied at checkout. You won’t need to enter any codes manually.

Your store credit will remain available in your account until you’re ready to use it.

We hope you’ll find something you truly love from our collection the next time you visit.


Step 4 — Shipping Guidance
Adapt the shipping guidance slightly based on the region and return type, using the language below as a guide.

Australia
We recommend purchasing tracking so your return can be processed efficiently.


United States
Please purchase tracking and hold on to your shipping receipt until your exchange has been completed.


Step 5 — Closing
Always end the email with the following line:

If there’s anything else you need, please just let me know.


Quick Reference: Email Structure at a Glance

Return Options Email
Opening + feedback request (unless customer already confirmed they want to proceed)
Sizing assistance if relevant
Policy explanation if applicable (observation, explanation, options)
Numbered return options (exactly as provided by the system)
Closing

Return Instructions Email
Opening (acknowledge confirmation)
Return instructions block (portal link + address + processing time, copied exactly from system)
Store credit redemption instructions (store credit only)
Shipping guidance
Closing


"""