from flask import Flask, render_template, request, jsonify
from ddgs import DDGS
import requests
from bs4 import BeautifulSoup
import re
import time
import os

app = Flask(__name__)

# ==================== ЛОГИКА ИИ ====================

def duckduckgo_search(query: str, num_results: int = 5):
    results = []
    try:
        with DDGS() as ddgs:
            for result in ddgs.text(query, max_results=num_results, region='ru-ru'):
                if re.search('[а-яА-Я]', result.get('title', '')) or re.search('[а-яА-Я]', result.get('body', '')):
                    results.append({
                        'title': result.get('title', ''),
                        'link': result.get('href', ''),
                        'snippet': result.get('body', '')
                    })
        return results
    except Exception as e:
        print(f"Ошибка поиска: {e}")
        return []

def fetch_page_text(url: str, max_chars: int = 3000):
    try:
        time.sleep(1)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        for script in soup(["script", "style", "nav", "footer"]):
            script.decompose()
        text = soup.get_text(separator=' ', strip=True)
        text = re.sub(r'\s+', ' ', text)
        if len(text) > max_chars:
            text = text[:max_chars] + "..."
        return text
    except Exception as e:
        print(f"Ошибка чтения {url}: {e}")
        return ""

def find_relevant_text(query: str, context: str) -> str:
    if not context or len(context) < 50:
        return "Недостаточно информации."
    sentences = re.split(r'[.!?]+', context)
    query_words = {w for w in query.lower().split() if w not in {'это','как','что','кто'} and len(w)>2}
    scored = []
    for sent in sentences:
        sent = sent.strip()
        if len(sent) < 20:
            continue
        matches = sum(1 for w in query_words if w in sent.lower())
        if matches > 0:
            scored.append((matches / (1 + len(sent.split())/50), sent))
    scored.sort(reverse=True)
    if scored:
        return ". ".join([s for _, s in scored[:5]])
    return context[:300] + "..."

def ask_with_search(query: str) -> dict:
    results = duckduckgo_search(query)
    if not results:
        return {'answer': '❌ Не удалось найти информацию', 'sources': []}
    
    context_parts = []
    sources = []
    
    for r in results[:3]:
        text = fetch_page_text(r['link'])
        if text and len(text) > 100:
            context_parts.append(text)
            sources.append({'title': r['title'][:50], 'link': r['link']})
    
    if not context_parts:
        return {'answer': '❌ Не удалось прочитать страницы', 'sources': sources}
    
    answer = find_relevant_text(query, " ".join(context_parts))
    return {'answer': answer, 'sources': sources}

# ==================== ВЕБ-ИНТЕРФЕЙС ====================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/ask', methods=['POST'])
def ask():
    data = request.json
    question = data.get('question', '')
    if not question:
        return jsonify({'error': 'Введите вопрос'})
    
    result = ask_with_search(question)
    return jsonify(result)

if __name__ == '__main__':
    print("=" * 50)
    print("🦆 ИИ-помощник с интернетом")
    print("=" * 50)
    print("🌐 Откройте в браузере: http://127.0.0.1:5000")
    print("💡 Нажмите Ctrl+C для остановки")
    print("=" * 50)
    app.run(debug=True)