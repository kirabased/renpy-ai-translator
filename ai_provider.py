import os
import requests
import json
import re
import time
from tqdm import tqdm

# Carrega configs do arquivo JSON
def load_config():
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

# Carrega os provedores do arquivo JSON
def load_providers():
    try:
        with open('providers.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"[ERRO] Falha ao carregar providers.json: {e}")
        return []

PROVIDERS = load_providers()
current_provider_index = 0
current_key_index = 0

def get_current_provider():
    # Recarrega para pegar atualizações da Web em tempo real
    global PROVIDERS
    PROVIDERS = load_providers()
    if not PROVIDERS:
        return None
    global current_provider_index
    if current_provider_index >= len(PROVIDERS):
        current_provider_index = 0
    return PROVIDERS[current_provider_index]

def get_current_key():
    provider = get_current_provider()
    if not provider: return ""
    
    global current_key_index
    # Suporta formato web novo (api_key) ou formato antigo (keys array)
    if "api_key" in provider: return provider["api_key"]
    
    if "keys" in provider and provider["keys"]:
        if current_key_index >= len(provider["keys"]):
            current_key_index = 0
        return provider["keys"][current_key_index]
    return ""

def rotate_key():
    global current_provider_index, current_key_index
    PROVIDERS = load_providers()
    if not PROVIDERS: return False
    
    cfg = load_config()
    if cfg.get("smart_rotation", True) == False:
        tqdm.write("  [SYSTEM] Smart Rotation disabled. Waiting for local cooldown...")
        return True
        
    provider = PROVIDERS[current_provider_index]
    
    # Se o provedor atual tiver múltiplas chaves, avança para a próxima chave
    if "keys" in provider and provider["keys"] and current_key_index + 1 < len(provider["keys"]):
        current_key_index += 1
        tqdm.write(f"  [SYSTEM] Switching to key {current_key_index + 1}/{len(provider['keys'])} of provider {provider.get('name', 'Unknown')}...")
        return False
    
    # Se acabaram as chaves do provedor atual, reseta o índice de chaves e muda de provedor
    current_key_index = 0
    current_provider_index = (current_provider_index + 1) % len(PROVIDERS)
    
    new_provider = PROVIDERS[current_provider_index]
    tqdm.write(f"  [SYSTEM] Switching to provider {new_provider.get('name', 'Unknown')}...")
    
    return current_provider_index == 0

def get_system_prompt():
    cfg = load_config()
    return cfg.get("system_prompt", "")


last_cloud_ping = 0

def ping_cloud_apis():
    """Faz um ping rápido (tentando se conectar à primeira API da nuvem)"""
    for prov in PROVIDERS:
        if not prov.get("is_local", False):
            url = prov.get("url", "https://openrouter.ai/api/v1")
            # Tenta um GET simples no domínio raiz ou endpoint de models para checar conectividade
            try:
                base_url = "/".join(url.split("/")[:3]) # Pega só o https://dominio.com
                # O ping pode falhar por auth, mas se retornar 401 ou 200, significa que o SERVIDOR está online!
                resp = requests.get(base_url, timeout=5)
                # Se respondeu qualquer coisa, está vivo (sem erro de rede/timeout)
                return True
            except Exception:
                pass
    return False

def translate_batch(texts, save_callback=None):
    if not texts:
        return []

    delimiter = "\n---|||---\n"
    combined_text = delimiter.join(texts)
    
    headers = {
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "placeholder",
        "stream": False,
        "messages": [
            {"role": "system", "content": get_system_prompt()},
            {"role": "user", "content": f"Translate the following text blocks, separated exactly by {delimiter.strip()}:\n\n{combined_text}"}
        ],
        "temperature": 0.3
    }
    
    max_api_retries = 20
    for attempt in range(max_api_retries):
        global current_provider_index, last_cloud_ping
        provider = get_current_provider()
        if not provider:
            return [""] * len(texts)
            
        current_url = provider.get("url", "https://openrouter.ai/api/v1")
        current_model = provider.get("model", "claude-haiku-4-5")
        current_key = get_current_key()
        is_local = provider.get("is_local", False)
        
        # === LÓGICA LOCAL E HÍBRIDA ===
        if is_local:
            translated_texts = []
            cloud_recovered = False
            
            tqdm.write(f"  [LOCAL] Starting local processing ({current_model})...")
            
            for i, text in enumerate(texts):
                # Ping a cada 30 segundos
                if time.time() - last_cloud_ping > 30:
                    last_cloud_ping = time.time()
                    if ping_cloud_apis():
                        cloud_recovered = True
                        break
                
                # Traduz a frase localmente
                res = translate_single(text)
                if not res:
                    res = ""
                translated_texts.append(res)
                
                # Salva o progresso imediatamente usando o callback
                if save_callback:
                    save_callback(i, res)
            
            if cloud_recovered:
                remaining_texts = texts[len(translated_texts):]
                current_provider_index = 0 # Força volta para a nuvem
                global current_key_index
                current_key_index = 0
                
                if remaining_texts:
                    tqdm.write(f"  [SYSTEM] Cloud API is back! Sending the {len(remaining_texts)} remaining sentences to the cloud...")
                    cloud_translations = translate_batch(remaining_texts, save_callback=save_callback)
                    return translated_texts + cloud_translations
                else:
                    return translated_texts
            else:
                return translated_texts
        # ==============================
        
        endpoint = f"{current_url}/chat/completions"
        payload["model"] = current_model
        
        try:
            headers["Authorization"] = f"Bearer {current_key}"
            tqdm.write(f"  [SYSTEM] Requesting batch for {provider.get('name', 'Unknown')} ({current_model})...")
            
            response = requests.post(endpoint, headers=headers, json=payload, timeout=180)
            response.encoding = 'utf-8'
            
            if response.status_code == 200:
                tqdm.write(f"  [SYSTEM] Success! Translation completed via {provider.get('name', 'Unknown')}.")
                result_text = ""
                
                if response.text.strip().startswith("data:"):
                    for line in response.text.splitlines():
                        line = line.strip()
                        if line.startswith("data: ") and line != "data: [DONE]":
                            try:
                                chunk = json.loads(line[6:])
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                if "content" in delta:
                                    result_text += delta["content"]
                                elif "message" in chunk.get("choices", [{}])[0] and "content" in chunk["choices"][0]["message"]:
                                    result_text += chunk["choices"][0]["message"]["content"]
                            except Exception:
                                pass
                else:
                    try:
                        data = response.json()
                        result_text = data['choices'][0]['message']['content']
                    except Exception:
                        print(f"[API ERROR] Response is not valid JSON. The server sent:\n{response.text[:500]}")
                        return [""] * len(texts)
                    
                result_text = result_text.strip()
                translated_texts = result_text.split(delimiter.strip())
                translated_texts = [t.strip() for t in translated_texts]
                
                if len(translated_texts) != len(texts):
                    tqdm.write(f"\n[WARNING] AI merged the dialogues and broke the batch. Starting individual rescue mode...")
                    individual_translations = []
                    for i, t in enumerate(tqdm(texts, desc="Individual Rescue", unit="sentence", leave=False, position=1)):
                        res = translate_single(t)
                        individual_translations.append(res)
                        if save_callback:
                            save_callback(i, res)
                        time.sleep(1)
                    return individual_translations
                    
                return translated_texts
                
            elif response.status_code in [429, 502, 503, 401]:
                if response.status_code == 429:
                    tqdm.write(f"  [WARNING] Key out of credits or daily limit reached (429).")
                elif response.status_code == 401:
                    tqdm.write(f"  [WARNING] Invalid key (401).")
                else:
                    tqdm.write(f"  [WARNING] AI server overloaded or unavailable ({response.status_code}).")
                    
                is_full_loop = rotate_key()
                if is_full_loop:
                    tqdm.write("  [WARNING] All keys and providers failed.")
                    for _ in tqdm(range(120), desc="  Cooling down API (2 min)", unit="s", leave=False, position=1):
                        time.sleep(1)
                continue
                
            else:
                tqdm.write(f"  [ERROR] Unexpected API error: {response.status_code} - {response.text}")
                return [""] * len(texts)
                
        except Exception as e:
            tqdm.write(f"  [ERROR] Server connection error: {e}")
            is_full_loop = rotate_key()
            if is_full_loop:
                tqdm.write("  [WARNING] General connection failure.")
                for _ in tqdm(range(120), desc="  Cooling down Connection (2 min)", unit="s", leave=False, position=1):
                    time.sleep(1)
            continue
            
    return [""] * len(texts)

def translate_single(text):
    """Traduz um único texto (Fallback)."""
    provider = get_current_provider()
    if not provider:
        return text
        
    current_url = provider.get("url", "https://openrouter.ai/api/v1")
    current_model = provider.get("model", "claude-haiku-4-5")
    current_key = get_current_key()
    
    headers = {
        "Authorization": f"Bearer {current_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": current_model,
        "messages": [
            {"role": "system", "content": get_system_prompt()},
            {"role": "user", "content": text}
        ],
        "temperature": 0.3
    }
    endpoint = f"{current_url}/chat/completions"
    try:
        response = requests.post(endpoint, headers=headers, json=payload, timeout=120)
        response.encoding = 'utf-8'
        if response.status_code == 200:
            if response.text.strip().startswith("data:"):
                result_text = ""
                for line in response.text.splitlines():
                    line = line.strip()
                    if line.startswith("data: ") and line != "data: [DONE]":
                        try:
                            chunk = json.loads(line[6:])
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            if "content" in delta:
                                result_text += delta["content"]
                        except Exception:
                            pass
                return result_text.strip()
            else:
                return response.json()['choices'][0]['message']['content'].strip()
    except Exception:
        pass
    return text
