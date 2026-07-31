# Ren'Py Game Translator

An automated and intelligent tool for translating visual novels made in the Ren'Py engine. It uses AI providers to translate in-game dialogue and menus while perfectly preserving the game's code, variables, formatting tags, and syntax.

## 🌟 Features
- **Smart Parsing**: Automatically extracts translatable strings from `.rpy` files without breaking Ren'Py syntax.
- **Code Preservation**: Ignores system lines, python code blocks, and preserves variables (e.g. `[player_name]`) and tags (e.g. `{w=2.0}`).
- **Multiple Providers & Key Rotation**: Supports adding multiple AI providers (OpenRouter, Gemini, Local models, etc.) and seamlessly rotates between multiple API keys. If a key runs out of balance or hits a rate limit, the tool automatically switches to the next one!
- **Crash Resilience**: Translates in batches and saves progress in real-time. If you stop the script or lose internet connection, it resumes exactly from where it left off.
- **Clean Output**: Leaves your original files untouched. Automatically outputs the translated `.rpy` files to a `tl_output` folder, perfectly mimicking your original directory structure.

## ⚙️ Setup & Configuration

1. **Clone or Download** the project.
2. **Install requirements**:
   ```bash
   pip install -r requirements.txt
   ```
3. **Set up `providers.json`**:
   Rename the example file to `providers.json`. Inside, you can configure multiple providers and an array of keys for each. The script will automatically rotate through the keys if one fails or runs out of credits.
   ```json
   [
       {
           "name": "OpenRouter",
           "url": "https://openrouter.ai/api/v1",
           "model": "google/gemini-pro",
           "keys": [
               "YOUR_KEY_1",
               "YOUR_KEY_2"
           ]
       }
   ]
   ```
5. **Set up your `translation files`**:
   Extract the `translation files` of your game with the [`Ren'Py Engine`](https://www.renpy.org/latest.html) "Generate Translations" function.
6. **Set up `config.json`**:
   Rename the example file to `config.json`. Set the `input_folder` to the path where your extracted `.rpy` files are located.

### 📝 Example System Prompt (English)
You can customize the `system_prompt` inside `config.json` to guide the AI's translation style. Here is a generic example for localizing a game into English (just paste this inside your `config.json`):

```json
"system_prompt": "You are a professional translator localizing a visual novel (Ren'Py) into English.\n\nYOUR TRANSLATION RULES:\n1. NATURAL TONE: The translation must be fluid and natural, adapting idioms into proper English equivalents.\n2. CONTEXT: Maintain the original tone of the sentence (whether serious, comedic, formal, or informal).\n3. PRESERVE CODE: It is STRICTLY MANDATORY to keep all Ren'Py formatting tags perfectly intact exactly where they are (like [var], {b}, {w=2.0}, \\n, etc.). NEVER translate the variable names inside brackets.\n4. DIRECT OUTPUT: Return ONLY the translated text. Do not add extra quotes, notes, explanations, or introductions."
```

## 🚀 Usage

Once your `.rpy` files are in the `input_folder` and your configuration is set, simply run:

```bash
python translator.py
```

- The script will read the files, send dialogue in batches to the AI, and save the translated versions in the `tl_output` folder.
- Temporary state files are managed in a `delete_after_translate` folder, which is automatically deleted upon 100% completion.
- You can stop the script at any time by pressing `CTRL+C`. When you restart it, it will pick up exactly where it left off.
