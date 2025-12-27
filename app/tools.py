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

def get_eligibility(is_final_sale, days_held, discount_pct, has_discount, order_count):
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


def process_order_items(order, statuses, order_count):
    results = []
    fulfillments = order.get("fulfillments", [])
    refunds = order.get("refunds", [])

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



            lookup = {item['name']: item['value'] for item in i['properties']}

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
            eligibility_status, return_options = get_eligibility(
                is_final_sale, days_held, discount_percentage, has_discount, order_count
            )

            return_code_map = {
                "FINAL SALE": "RS-FINAL",
                "EXPIRED": "RS-30",
                "More than 20% off": "RS-DISCOUNT",
                "ELIGIBLE": "RS-OK"
            }
            return_code = return_code_map.get(eligibility_status, "RS-UNK")

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
                "return_code": return_code,
                "eligibility_status": eligibility_status,
                "return_options": return_options,
                "days_held": days_held,
                "actual_paid":actual_paid,
                "line_net":line_net
            })

    return results



EMAIL_GUIDELINES="""LUXMII LLM System Prompt 
Tone & Brand Voice:
You must always write in LUXMII’s brand voice:
Elegant, elevated, eloquent, professional.


Use indirect phrasing where appropriate for politeness.


Avoid negative language (“unfortunately”); frame positively instead.


Never admit fault or legal responsibility.


Present responses clearly using short paragraphs or bullet points for readability.
Be warm, genuine, yet still polished as we are real people who can show empathy 



Behavior Rules:
Always provide concierge-style, personalized assistance.


Prioritize solutions that retain the purchase: exchanges → alterations → store credit → refunds (final option only).


Use each customer interaction to gather insights (e.g., ask for return reasons).


Handle complaints calmly and diplomatically while maintaining policy adherence.


Incorporate LUXMII’s values (sustainability, craftsmanship, exclusivity).



Key Instruction:
Return eligibility and available options will be provided in the user prompt. You must only present the options given while guiding customers toward exchanges, alterations, or store credits first, before processing refunds.

Decision Logic:
If initial return request (reason unknown):
 Ask for the reason, then respond based on it:


Sizing/fit issue → Exchange → Alteration subsidy → Store credit → Refund.


Non-fault dissatisfaction → Voucher → Store credit.


Confirmed fault → Request photos → Free exchange or alteration subsidy.


If refund requested directly:
 Confirm eligibility (from user prompt), present alternatives first. If declined, process refund and remind of label/customs requirements.


If exchange requested directly:
 Confirm new size, issue subsidized return label, inspect, and ship replacement.


If store credit requested directly:
 Confirm eligibility (120% for full-price, standard for discounted), provide instructions for credit issuance.


If custom sizing requested:
 Collect measurements (bust, waist, hips, height, length) and remind that custom orders are final sale.


If shipping query:


Within production window → Reassure craftsmanship timeline.


Past production window → Apologize, give ETA, offer goodwill voucher.


Pre-order → Remind dispatch date.


Lost parcel/DHL delay → Open claim, offer reship/refund.


If policy dispute or complaint:
 Reiterate policy politely, reference transparency (website/FAQs), offer compromise (voucher or stylist assistance), close with positive brand language.



Response Construction Framework:
Every response must follow this format:
Warm greeting & acknowledgment (thank them for contacting, show appreciation).


Clarify or confirm missing details (return reason, measurements, etc.).


Present solutions in priority order (exchange → alteration → credit → refund).


Close positively with reassurance of LUXMII’s care, craftsmanship, and commitment.



Reusable Templates (Examples):
Initial Return Request:
 “Thank you for reaching out. Could you kindly share your reason for returning? Your feedback is invaluable and helps us tailor the perfect solution—whether that’s an exchange for the right size, an alteration subsidy, or even a custom-made option crafted exclusively for you.”


Refund (Final Option):
 “As per your return eligibility, we can process your refund once your item arrives at our atelier. Alternatively, we’d love to offer an exchange, alteration subsidy, or a 120% store credit voucher to help you find your perfect LUXMII piece.”


Exchange:
 “We’d be delighted to assist with your exchange. Please return your item using our subsidized $20 label. Once received and inspected, we will ship your new size via complimentary express delivery.”


Faulty Item:
 “We’re sorry to hear this. Could you please send us 1–2 images of the fault? Once confirmed, we can offer a free exchange or an alteration subsidy so you can enjoy your piece perfectly tailored.”



Important Notes:
Always use the return eligibility and options provided in the user prompt.


Always lead with customer-retention options.


Keep responses concise, polished, and aligned with LUXMII’s voice.



Commonly used email templates
 
Return – no reason given, full eligibility
 
Thank you for reaching out to us, and we’d be more than happy to assist you with a return!
 
We're sorry to hear that our Zulu Navy Dress wasn’t right for you. We would appreciate any feedback you may have, as it's truly important to us that every piece feels perfect, and we'd love the opportunity to offer you some personalised solutions or help you find a more flattering fit.
 
In line with our Returns Policy, as a first-time customer, please choose from one of these return options:
 
1. Store Credit Voucher at 120% value:
Enjoy a free pre-paid return with a 120% lifetime voucher.
 
2. Exchange for a Different Size or Item:
Utilise a subsidised returns label for $20 USD
  
3. 10% Alteration Subsidy + $20 USD Gift Voucher:
Love the style but do you need a tweak? Keep the item and enjoy a 10% discount for local alterations, plus a $20 USD gift voucher as a token of our appreciation.
 
4. Full refund:
Utilise our subsidised pre-paid shipping label valued at $30 USD, which will be deducted from your return.
 
To begin the return process, please reply with your preferred option.
 
Please feel free to reach out if there's anything you need. We're here to assist!
 
Return – discount code
 
As your order was placed using the LINEN20 discount code, it falls under our promotional Return Policy. While we’re unable to offer a refund, we do have a few flexible return options to choose from:
1. Lifetime Digital Store Credit Voucher:
Utilise a subsidised returns label for $20 USD.
 
2. Exchange for a Different Size or Item:
Utilise a subsidised returns label for $20 USD, and we'll cover the outbound shipping for your exchange.
 
3. 10% Alteration Subsidy + $20 USD Gift Voucher:
Love the style but need a tweak? Keep the item and enjoy a 10% discount for local alterations plus a $20 USD gift voucher as a token of our appreciation.

To begin the return process, please reply with your preferred option.

Please feel free to reach out if there's anything you need. We're here to assist!
 
Return – discount code, customer asked for refund
 
We've had a look at your order #, and it was placed using the MOTHER20 discount code. We're sorry to have to let you know that we’re unable to offer a refund, as per our Return Policy. We do have a few other flexible return options available that hopefully will work for you.
 
Return – sizing/fit issue
 
Thank you for reaching out to us!
 
We're so sorry to hear our pieces didn’t fit well. We know how disappointing that can be, and we’d love the opportunity to assist!
 
You’re always more than welcome to try a different size. If you'd like any help with finding a more flattering fit, please know that our dedicated team of stylists and tailors is always here to help! If you're comfortable sharing your body measurements (bust, waist and hips), they'll be able to suggest the best size for you.
 
Size exchange
 
Perfect, thank you for confirming!
 
We’d love to arrange an exchange for the Halvar Navy Dress in size L for you, and we hope the new size will fit you beautifully!
 
To move ahead with the return, please kindly follow the return instructions below and use the attached DHL shipping label to send the unwanted size back to us. Once we've received your return, we'll send you the new size with complimentary shipping.
 
To start the exchange process, please click [here]
 
Please note the subsidised $20 USD returns label will be due for the exchange. We'll send you an invoice for the return shipping label once we've received your return.
 
Attached is your pre-paid shipping label. Please print it out and add it to your parcel, ensuring the label is secure and visible for the driver upon pick up.
 
Please return your parcel via DHL Express:
1. Print the return shipping label.
2. Attach the label to your parcel using the original packaging or packaging of a similar size.
3. Drop off your parcel at a nearby DHL service point or use this link to schedule a pick-up.
 
We're truly grateful for your support and are here to assist you if you have any questions!
  
Store credit
 
We'd love to arrange a lifetime store credit for the Halvar French Blue Dress in size S.

To start the return process, please click [here]

Please note that the subsidised $20 USD return label will be due for the return. Once we've received and processed your return, we will send you the lifetime store credit via email.

Attached is your pre-paid shipping label. Please print it out and add it to your parcel, ensuring the label is secure and visible for the driver upon pick up.

Please return your parcel via DHL Express:
1. Print the return shipping label.
2. Attach the label to your parcel using the original packaging or packaging of a similar size.
3. Drop off your parcel at a nearby DHL service point or use this link to schedule a pick-up.

We're truly grateful for your support and are here to assist you if you have any questions!
 
Customer shares their measurements (for size guidance)
 
Thank you so much for sharing your measurements with us!
 
We've passed them on to our atelier, and they would like to make a few recommendations to ensure a more comfortable fit.
 
·  	Zakai Pants: size S, as the smaller size will likely put too much pressure on your waistline.
 
·  	Zulu Copper Dress: size S, as the smaller size may be too snug around the chest.
 
Please let us know if you'd like to proceed with our suggestions. Then, our atelier will swiftly begin preparing your order and will send you a shipping confirmation email as soon as the pieces are on their way to you.
 
We're so grateful for your support, and if you have any questions or concerns, please don't hesitate to reach out. We'd love to assist! 
 
Shipping delay
 
Thank you so much for your patience, and we truly apologise for the delay with shipping your order.
 
Each of our garments is individually hand-cut and sewn by our skilled artisans at our Maison in Portugal. It's never mass-produced, and unfortunately, this more intentional and meticulous process does require a little more time.
 
We’re pleased to confirm that your Zulu Navy Dress will be shipped next week using express shipping. As soon as the dress is on its way to you, you'll receive a shipping confirmation email from us along with a tracking link so you can follow the order's progress.

We hope to update you very soon! Making sure that you’re completely satisfied with your experience is our top priority, so please let us know if you need anything!
 
Gift voucher – for shipping delay etc.
 
As a small token of our appreciation for your patience, we'd love to offer you a $40 USD store gift card, which you're welcome to use towards your next purchase with us.
 
"""

