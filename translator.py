import os
import re
import json
import glob
from tqdm import tqdm
from ai_provider import translate_batch
import traceback

stop_requested = False

def extract_translatable_string(line):
    if not line.strip() or line.strip().startswith('#'): return None
    if line.strip().startswith('$'): return None
    
    ignore_keywords = [
        'define', 'default', 'image', 'transform', 'screen', 'style', 'label', 
        'jump', 'call', 'scene', 'show', 'hide', 'play', 'stop', 'pause', 'window', 'return', 'pass',
        'old', 'new', 'voice', 'nvl', 'music', 'sound'
    ]
    first_word = line.strip().split(' ')[0]
    if first_word in ignore_keywords: return None
        
    menu_match = re.match(r'^\s*"(.*?)"\s*:$', line)
    if menu_match: return menu_match
        
    dialogue_match = re.match(r'^\s*(?:[a-zA-Z0-9_]+\s+)*"(.*?)"(?:\s+with\s+[a-zA-Z0-9_]+)?\s*$', line)
    if dialogue_match:
        quote_start = line.find('"')
        if '=' in line[:quote_start]: return None
        return dialogue_match
    return None

def process_file(filepath, input_folder):
    if stop_requested: return
    filename = os.path.basename(filepath)
    rel_path = os.path.relpath(filepath, input_folder)
    out_filepath = os.path.join("tl_output", rel_path)
    state_filepath = os.path.join("delete_after_translate", rel_path + ".state.json")
    
    # Cria os diretórios se não existirem
    os.makedirs(os.path.dirname(out_filepath), exist_ok=True)
    os.makedirs(os.path.dirname(state_filepath), exist_ok=True)
    
    tqdm.write(f"\n--- [GENERIC REN'PY] {filename} ---")
    
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    blocks = []
    
    skip_lines = set()
    for i, line in enumerate(lines):
        if i in skip_lines:
            continue
            
        # Detecta blocos "translate strings" do SDK (old "texto" seguido de new "")
        old_match = re.match(r'^(\s*)old\s+"(.*?)"\s*$', line)
        if old_match and i + 1 < len(lines):
            next_line = lines[i+1]
            new_match = re.match(r'^(\s*)new\s+"(.*)"\s*$', next_line)
            if new_match:
                text_to_translate = old_match.group(2)
                if text_to_translate.strip():
                    blocks.append({
                        'line_idx': i + 1,
                        'original_line': next_line,
                        'text_to_translate': text_to_translate,
                        'start_idx': new_match.start(2),
                        'end_idx': new_match.end(2)
                    })
                skip_lines.add(i + 1)
                continue
                
        # Detecta blocos de diálogo do SDK (# char "texto original" seguido de char "")
        dialogue_comment_match = re.match(r'^(\s*)#\s*((?:[a-zA-Z0-9_]+\s+)*)"(.*?)"\s*$', line)
        if dialogue_comment_match:
            prefix = dialogue_comment_match.group(2) or ""
            next_regex = r'^(\s*)' + re.escape(prefix) + r'"(.*)"\s*$'
            
            found = False
            # Busca nas próximas 4 linhas (para pular comandos voice/sound no meio do bloco)
            for offset in range(1, 5):
                if i + offset >= len(lines): break
                lookahead_line = lines[i+offset]
                new_dialogue_match = re.match(next_regex, lookahead_line)
                
                if new_dialogue_match:
                    text_to_translate = dialogue_comment_match.group(3)
                    if text_to_translate.strip():
                        blocks.append({
                            'line_idx': i + offset,
                            'original_line': lookahead_line,
                            'text_to_translate': text_to_translate,
                            'start_idx': new_dialogue_match.start(2),
                            'end_idx': new_dialogue_match.end(2)
                        })
                    skip_lines.add(i + offset)
                    found = True
                    break
                    
            if found:
                continue
                
        match = extract_translatable_string(line)
        if match:
            text = match.group(1)
            # Ignora strings vazias ou só com espaços
            if not text.strip(): continue
                
            start_idx = match.start(1)
            end_idx = match.end(1)
            
            blocks.append({
                'line_idx': i,
                'original_line': line,
                'text_to_translate': text,
                'start_idx': start_idx,
                'end_idx': end_idx
            })
            
    if not blocks:
        tqdm.write(f"No translatable text found in {filename}.")
        return

    tqdm.write(f"Total of {len(blocks)} blocks found in {filename}.")
    
    texts_to_translate = [b['text_to_translate'] for b in blocks]
    chunk_size = 20
    
    start_i = 0
    if os.path.exists(out_filepath) and os.path.exists(state_filepath):
        with open(out_filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        with open(state_filepath, 'r', encoding='utf-8') as f:
            state = json.load(f)
            start_i = state.get("last_i", -chunk_size) + chunk_size
        tqdm.write(f"[{filename}] Resuming translation from existing file (batch starting at {start_i})...")
    else:
        # Cria o arquivo inicial para acompanhamento em tempo real
        with open(out_filepath, 'w', encoding='utf-8') as f:
            f.writelines(lines)
            
    for i in tqdm(range(start_i, len(texts_to_translate), chunk_size), desc=f"Batches ({filename})", unit="batch", leave=False):
        if stop_requested: return
        chunk = texts_to_translate[i:i+chunk_size]
        
        try:
            translated_chunk = translate_batch(chunk)
            
            for j, translated_text in enumerate(translated_chunk):
                global_idx = i + j
                if global_idx < len(blocks):
                    if translated_text.strip():
                        # Corrige as aspas duplas geradas pela IA para simples, para não quebrar a sintaxe do Ren'Py
                        translated_text_fixed = translated_text.replace('"', "'")
                        
                        b = blocks[global_idx]
                        original = b['original_line']
                        # Substitui a exata posição da string extraída
                        new_line = original[:b['start_idx']] + translated_text_fixed + original[b['end_idx']:]
                        lines[b['line_idx']] = new_line
                        
            # Salva o progresso
            with open(out_filepath, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            with open(state_filepath, 'w', encoding='utf-8') as f:
                json.dump({"last_i": i}, f)
                
        except Exception as e:
            tqdm.write(f"[{filename}] Error in batch {i//chunk_size}: {str(e)}")
            traceback.print_exc()

    tqdm.write(f"[{filename}] Completed successfully!")

def load_config():
    with open('config.json', 'r', encoding='utf-8') as f:
        return json.load(f)

def run():
    global stop_requested
    try:
        cfg = load_config()
        input_folder = cfg.get("input_folder", "./input")
        
        tqdm.write(f"Starting generic translation in folder: {input_folder}")
        rpy_files = glob.glob(os.path.join(input_folder, "**", "*.rpy"), recursive=True)
        # Filtra os arquivos que já são de saída (terminados em _ptbr.rpy)
        rpy_files = [f for f in rpy_files if not f.endswith("_ptbr.rpy")]
        
        for filepath in rpy_files:
            if stop_requested: break
            process_file(filepath, input_folder)
            
        if not stop_requested:
            tqdm.write("\nBatch translation of all files completed!")
            if os.path.exists("delete_after_translate"):
                import shutil
                shutil.rmtree("delete_after_translate")
                tqdm.write("Temporary files (.state.json) successfully deleted.")
    except KeyboardInterrupt:
        stop_requested = True
        tqdm.write("\nProcess interrupted by user.")
    except Exception as e:
        tqdm.write(f"\nCritical error: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    run()
