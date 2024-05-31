from decimal import Decimal
import os
import requests
from dotenv import load_dotenv
from telebot.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
import telebot
from stellar_sdk import Keypair, Server, Signer, TransactionBuilder, Network, Asset

load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_API_KEY")
bot = telebot.TeleBot(BOT_TOKEN)

process_states = {}

# Initialize Stellar server
server = Server("https://horizon-testnet.stellar.org")

def generate_keypair():
    pair = Keypair.random()
    return pair.secret, pair.public_key

def create_account(public_key):
    response = requests.get(f"https://friendbot.stellar.org?addr={public_key}")
    return response.status_code == 200

def add_account(root_private_key, secondary_private_key):
    root_keypair = Keypair.from_secret(root_private_key)
    root_account = server.load_account(account_id=root_keypair.public_key)
    secondary_keypair = Keypair.from_secret(secondary_private_key)
    secondary_signer = Signer.ed25519_public_key(account_id=secondary_keypair.public_key, weight=1)
    transaction = (
        TransactionBuilder(
            source_account=root_account,
            network_passphrase=Network.TESTNET_NETWORK_PASSPHRASE,
            base_fee=100,
        )
        .append_set_options_op(
            master_weight=1,
            low_threshold=1,
            med_threshold=2,
            high_threshold=2,
            signer=secondary_signer,
        )
        .set_timeout(30)
        .build()
    )
    transaction.sign(root_keypair)
    response = server.submit_transaction(transaction)
    return response

def get_private_key(chat_id, user_id):
    if chat_id in process_states and user_id in process_states[chat_id]["public_keys"]:
        return process_states[chat_id]["public_keys"][user_id]["secret"]
    return None

def get_public_key(chat_id, user_id):
    if chat_id in process_states and user_id in process_states[chat_id]["public_keys"]:
        return process_states[chat_id]["public_keys"][user_id]["public_key"]
    return None

def create_transaction(source_public_key, destination_public_key, amount):
    source_account = server.load_account(source_public_key)
    base_fee = server.fetch_base_fee()
    transaction = (
        TransactionBuilder(
            source_account=source_account,
            network_passphrase=Network.TESTNET_NETWORK_PASSPHRASE,
            base_fee=base_fee,
        )
        .add_text_memo("Multisig transaction")
        .append_payment_op(destination=destination_public_key, amount=str(Decimal(amount)), asset=Asset.native())
        .set_timeout(30)
        .build()
    )
    return transaction

def submit_transaction(transaction):
    try:
        response = server.submit_transaction(transaction)
        return response
    except Exception as e:
        print(f"Transaction submission failed: {e}")
        return None

def generate_main_menu():
    return (f"*Multisig Stellar Bot*\n\n"
            f"Welcome! Here are the commands you can use:\n\n"
            f"*Commands:*\n"
            f"/start - Start the bot and create a new session.\n"
            f"/send - Send a transaction.\n"
            f"/add\\_co\\_signer - Add a co-signer.\n"
            f"/test - Test the bot.\n"
            f"/gen\\_keys - Generate new keys for the signer.\n"
            f"/import\\_keys - Use your own keys for the signer.\n"
            f"/private\\_key - Send your private key in a private message.\n")

@bot.message_handler(commands=["start"])
def start(message: Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    if user_id not in process_states:
        process_states[user_id] = {"private_chat_id": user_id}

    bot.send_message(chat_id, f"Welcome! You have been registered.\n\n{generate_main_menu()}", parse_mode="Markdown")

@bot.message_handler(commands=["gen_keys"])
def generate_keys(message: Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    secret, public_key = generate_keypair()
    process_states[chat_id] = {
        "active": True,
        "original_signer": user_id,
        "members": [user_id],
        "public_keys": {user_id: {"secret": secret, "public_key": public_key}},
        "transaction": None,
        "members_responded": set()
    }
    if create_account(public_key):
        bot.send_message(chat_id, f"Original signer added: {public_key}\n\n{generate_main_menu()}", parse_mode="Markdown")
    else:
        bot.send_message(chat_id, "Failed to create account for the original signer.")

@bot.message_handler(commands=["import_keys"])
def import_keys(message: Message):
    chat_id = message.chat.id
    bot.send_message(chat_id, "Please send your private key.")
    bot.register_next_step_handler(message, process_private_key)

def process_private_key(message: Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    private_key = message.text.strip()

    try:
        keypair = Keypair.from_secret(private_key)
        public_key = keypair.public_key
        process_states[chat_id] = {
            "active": True,
            "original_signer": user_id,
            "members": [user_id],
            "public_keys": {user_id: {"secret": private_key, "public_key": public_key}},
            "transaction": None,
            "members_responded": set()
        }
        bot.send_message(chat_id, f"Your keys have been added. Public key: {public_key}\n\n{generate_main_menu()}", parse_mode="Markdown")
    except Exception as e:
        bot.send_message(chat_id, "Invalid private key. Please try again.")
        bot.register_next_step_handler(message, process_private_key)

@bot.message_handler(commands=["private_key"])
def send_private_key(message: Message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    if user_id in process_states and "private_chat_id" in process_states[user_id]:
        private_chat_id = process_states[user_id]["private_chat_id"]
        private_key = get_private_key(chat_id, user_id)
        if private_key:
            bot.send_message(private_chat_id, f"Your private key: {private_key}")
            bot.reply_to(message, "Your private key has been sent to your private chat.")
        else:
            bot.reply_to(message, "No private key found for you in the current process.")
    else:
        bot.reply_to(message, "You are not registered for private messages. Please use /start to register.")


@bot.message_handler(commands=["add_co_signer"])
def add_co_signer(message: Message):
    chat_id = message.chat.id
    if chat_id not in process_states:
        bot.reply_to(message, "No active process. Please start with /start.")
        return

    bot.send_message(chat_id, "Co-signer: Please choose an option:\n/gen_keys_co_signer - Generate new keys\n/import_keys_co_signer - Use your own keys")

@bot.message_handler(commands=["gen_keys_co_signer"])
def add_co_signer_generate_keys(message: Message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    if user_id not in process_states[chat_id]["public_keys"]:
        secret, public_key = generate_keypair()
        process_states[chat_id]["members"].append(user_id)
        process_states[chat_id]["public_keys"][user_id] = {"secret": secret, "public_key": public_key}
        if create_account(public_key):
            root_private_key = process_states[chat_id]["public_keys"][process_states[chat_id]["original_signer"]]["secret"]
            add_account(root_private_key, secret)
            bot.reply_to(message, f"Co-signer added: {public_key}\n\n{generate_main_menu()}", parse_mode="Markdown")
        else:
            bot.reply_to(message, "Failed to create account for co-signer.")
    else:
        bot.reply_to(message, "You have already been added as a co-signer.")

@bot.message_handler(commands=["import_keys_co_signer"])
def add_co_signer_use_own_keys(message: Message):
    chat_id = message.chat.id
    bot.send_message(chat_id, "Co-signer: Please send your private key.")
    bot.register_next_step_handler(message, process_co_signer_private_key)

def process_co_signer_private_key(message: Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    private_key = message.text.strip()

    try:
        keypair = Keypair.from_secret(private_key)
        public_key = keypair.public_key
        if user_id not in process_states[chat_id]["public_keys"]:
            process_states[chat_id]["members"].append(user_id)
            process_states[chat_id]["public_keys"][user_id] = {"secret": private_key, "public_key": public_key}
            root_private_key = process_states[chat_id]["public_keys"][process_states[chat_id]["original_signer"]]["secret"]
            add_account(root_private_key, private_key)
            bot.send_message(chat_id, f"Co-signer added: {public_key}\n\n{generate_main_menu()}", parse_mode="Markdown")
        else:
            bot.reply_to(message, "You have already been added as a co-signer.")
    except Exception as e:
        bot.send_message(chat_id, "Invalid private key. Please try again.")
        bot.register_next_step_handler(message, process_co_signer_private_key)

@bot.message_handler(commands=["verify"])
def verify_members(message: Message):
    chat_id = message.chat.id
    if chat_id in process_states:
        admin_ids = [admin.user.id for admin in bot.get_chat_administrators(chat_id)]
        all_present = all(user_id in admin_ids for user_id in process_states[chat_id]["members"])
        if all_present:
            bot.reply_to(message, "All co-signers are present in the chat. Ready to create wallets.")
        else:
            bot.reply_to(message, "Not all co-signers are present in the chat.")
    else:
        bot.reply_to(message, "No active process found.")

@bot.message_handler(commands=["yes"])
def confirm_yes(message: Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    if chat_id in process_states and user_id in process_states[chat_id]["public_keys"]:
        process_states[chat_id]["members_responded"].add(user_id)
        if len(process_states[chat_id]["members_responded"]) == len(process_states[chat_id]["members"]):
            bot.send_message(chat_id, "All members have signed. Executing transaction...")
            execute_transaction(chat_id)
        else:
            remaining = len(process_states[chat_id]["members"]) - len(process_states[chat_id]["members_responded"])
            bot.send_message(chat_id, f"Waiting for {remaining} more members to respond.")
    else:
        bot.reply_to(message, "You are not a co-signer.")

@bot.message_handler(commands=["send"])
def send(message: Message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    # Ensure the message contains two arguments (destination public key and amount)
    try:
        _, destination_public_key, amount = message.text.split()
        amount = str(float(amount))  # Ensure the amount is a valid number and convert to string
    except ValueError:
        bot.reply_to(message, "Usage: /send <destination_public_key> <amount>")
        return

    if chat_id in process_states:
        process_states[chat_id]["transaction"] = {
            "destination_public_key": destination_public_key,
            "amount": amount
        }
        bot.send_message(chat_id, f"Transaction set to send {amount} XLM to {destination_public_key}.\nUse /yes to confirm and sign the transaction.")
    else:
        bot.reply_to(message, "No active process. Please start with /start.")

def execute_transaction(chat_id):
    if "transaction" not in process_states[chat_id]:
        bot.send_message(chat_id, "No transaction details found. Please use /send to set the transaction details.")
        return

    transaction_details = process_states[chat_id]["transaction"]
    source_public_key = process_states[chat_id]["public_keys"][process_states[chat_id]["original_signer"]]["public_key"]
    destination_public_key = transaction_details["destination_public_key"]
    amount = transaction_details["amount"]

    transaction = create_transaction(source_public_key, destination_public_key, amount)

    for user_id in process_states[chat_id]["members_responded"]:
        signer_secret = process_states[chat_id]["public_keys"][user_id]["secret"]
        signer_keypair = Keypair.from_secret(signer_secret)
        transaction.sign(signer_keypair)

    response = submit_transaction(transaction)
    response_message = f"Transaction submitted successfully!" if response else "Transaction submission failed."
    # print(response)

    # Split the message if it exceeds the character limit
    if len(response_message) > 4096:
        for i in range(0, len(response_message), 4096):
            bot.send_message(chat_id, response_message[i:i + 4096])
    else:
        bot.send_message(chat_id, response_message)


@bot.message_handler(commands=["no"])
def confirm_no(message: Message):
    chat_id = message.chat.id
    if chat_id in process_states:
        process_states[chat_id]["active"] = False
        bot.send_message(chat_id, "Process terminated due to a /no response.")
    else:
        bot.reply_to(message, "No active process found.")

@bot.message_handler(commands=["get_private_key"])
def get_private_key_handler(message: Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    private_key = get_private_key(chat_id, user_id)
    if private_key:
        bot.send_message(chat_id, f"Your private key: {private_key}")
    else:
        bot.reply_to(message, "No private key found for you in the current process.")

@bot.message_handler(commands=["get_public_key"])
def get_public_key_handler(message: Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    public_key = get_public_key(chat_id, user_id)
    if public_key:
        bot.send_message(chat_id, f"Your public key: {public_key}")
    else:
        bot.reply_to(message, "No public key found for you in the current process.")

@bot.message_handler(commands=["info"])
def test_process(message: Message):
    chat_id = message.chat.id
    if chat_id in process_states:
        response = "Current Co-signers and their account statuses:\n"
        for user_id, keys in process_states[chat_id]["public_keys"].items():
            user_info = bot.get_chat_member(chat_id, user_id).user
            response += f"User: {user_info.username} (ID: {user_id}) - Public Key: {keys['public_key']}\n"
        bot.send_message(chat_id, response)
    else:
        bot.reply_to(message, "No active process found.")

@bot.message_handler(func=lambda msg: True)
def echo_all(message: Message):
    bot.reply_to(message, message.text)

bot.infinity_polling()



