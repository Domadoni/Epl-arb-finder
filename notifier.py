import os, requests

def norm_book(n:str)->str:
    return n.strip().lower()

def is_betfair_exchange(name:str)->bool:
    return "betfair" in norm_book(name)

DEFAULT_PARTNERS = {"bet365","ladbrokes","william hill","boylesports","boyle sports","coral"}
def parse_partner_env()->set:
    raw = os.environ.get("PARTNER_BOOKS","").strip()
    if not raw:
        return DEFAULT_PARTNERS
    return {x.strip().lower() for x in raw.split(",") if x.strip()}

def is_partner_book(name:str, partners:set)->bool:
    return any(p in norm_book(name) for p in partners)

def telegram_send(bot_token, chat_id, text):
    try:
        requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage",
                      json={"chat_id": chat_id,"text":text},timeout=15).raise_for_status()
    except Exception as e:
        print("Telegram send failed:",e)

if __name__=="__main__":
    bot = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if bot and chat:
        telegram_send(bot, chat, "✅ Notifier test ok")
