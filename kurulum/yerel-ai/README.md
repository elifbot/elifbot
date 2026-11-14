# Yerel (çevrimdışı) AI kodlama kurulumu

Hedef: VS Code + Continue.dev + Ollama (Qwen2.5-Coder). API anahtarı gerektirmez.
Aider ve Tabby seçenek olarak eklenmiştir.

## 1. Ollama
- Windows/macOS: https://ollama.com/download
- Linux: `curl -fsSL https://ollama.com/install.sh | sh`

Model seçimi (RAM'e göre):
| Model | Yaklaşık RAM | Kullanım |
|---|---|---|
| `qwen2.5-coder:1.5b-base` | ~2 GB | otomatik tamamlama |
| `qwen2.5-coder:7b` | ~8 GB | sohbet, düzenleme |
| `qwen2.5-coder:14b` | ~16 GB | daha güçlü, yavaş |

```sh
ollama pull qwen2.5-coder:7b
ollama pull qwen2.5-coder:1.5b-base
ollama serve   # genelde zaten çalışır
```

## 2. Continue.dev (VS Code / JetBrains)
1. VS Code Marketplace'ten "Continue" eklentisini kurun.
2. `continue-config.yaml` dosyasını `~/.continue/config.yaml` olarak kopyalayın
   (Windows: `%USERPROFILE%\.continue\config.yaml`).
3. Sol kenar çubuğundaki Continue simgesini açın; model "Qwen2.5-Coder 7B" olarak görünmeli.

Komut satırı: `npm install -g @continuedev/cli` ardından `cn`.

## 3. Aider (terminal)
```sh
pip install aider-chat
cp kurulum/yerel-ai/aider.conf.yml .aider.conf.yml
export OLLAMA_API_BASE=http://127.0.0.1:11434
aider
```

## 4. Tabby (isteğe bağlı, Docker gerekir)
```sh
docker run -it -p 8080:8080 -v $HOME/.tabby:/data tabbyml/tabby serve --model StarCoder-1B --device cpu
```
Tabby, Ollama'nın kullandığı model havuzundan değil kendi model listesinden çeker.

## Notlar
- Bu kurulum yalnızca yerel model çalıştırır. Gerçek emir gönderen bir bileşen yoktur.
- ACARBOT kuralları (1000 USD kasa, 50 USD teminat, 10x, CROSS, −10 USD stop) değişmez; kod
  önerilerinde bu değerler `bot/v8/config.py` ile uyumlu tutulmalıdır.
