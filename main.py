from flask import Flask, render_template, request, jsonify
from ddgs import DDGS
import requests
from bs4 import BeautifulSoup
import re
import time
import os
import random
import json

app = Flask(__name__)

# Список User-Agent для обхода блокировок
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
]

def get_headers():
    return {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Cache-Control': 'max-age=0',
    }

def duckduckgo_search(query: str, num_results: int = 6):
    """Поиск через DuckDuckGo"""
    results = []
    try:
        print(f"🔍 Поиск: {query}")
        with DDGS() as ddgs:
            for result in ddgs.text(query, max_results=num_results):
                title = result.get('title', '').strip()
                body = result.get('body', '').strip()
                href = result.get('href', '')
                
                if not href:
                    continue
                
                # Проверяем наличие русского языка
                has_russian = re.search('[а-яА-Я]', title) or re.search('[а-яА-Я]', body)
                
                # Приоритет русскоязычным результатам
                if has_russian or len(results) < 3:
                    results.append({
                        'title': title if title else 'Источник',
                        'link': href,
                        'snippet': body if body else 'Нет описания'
                    })
                    if len(results) >= num_results:
                        break
        
        print(f"✅ Найдено: {len(results)} результатов")
        return results
    except Exception as e:
        print(f"❌ Ошибка поиска: {e}")
        return []

def fetch_page_text(url: str, max_chars: int = 3000):
    """Чтение страницы с обходом блокировок"""
    try:
        time.sleep(random.uniform(0.5, 1.5))
        
        session = requests.Session()
        response = session.get(url, headers=get_headers(), timeout=15, allow_redirects=True)
        response.raise_for_status()
        
        # Проверка на капчу
        if 'captcha' in response.text.lower() or 'access denied' in response.text.lower():
            return ""
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Удаляем мусор
        for tag in soup.find_all(['script', 'style', 'nav', 'footer', 'header', 'aside', 'form']):
            tag.decompose()
        
        # Ищем основной контент
        content = soup.find('main') or soup.find('article') or soup.find('div', class_=re.compile(r'content|post|entry|article'))
        
        if content:
            text = content.get_text(separator=' ', strip=True)
        else:
            text = soup.get_text(separator=' ', strip=True)
        
        # Очищаем текст
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'[©™®]', '', text)
        text = re.sub(r'\b\w{30,}\b', '', text)  # Убираем длинные слова
        
        # Если нет русского текста, пропускаем
        if not re.search('[а-яА-Я]', text):
            return ""
        
        if len(text) > max_chars:
            text = text[:max_chars] + "..."
        
        return text.strip()
        
    except Exception as e:
        print(f"⚠️ Не удалось прочитать: {url[:60]}... ({str(e)[:30]})")
        return ""

def find_best_answer(query: str, results: list) -> dict:
    """
    Находит лучший ответ, используя поисковые сниппеты и содержимое страниц
    """
    if not results:
        return {
            'answer': '❌ Не удалось найти информацию. Попробуйте переформулировать вопрос.',
            'sources': []
        }
    
    # Сначала пытаемся использовать сниппеты (быстрый вариант)
    snippets = []
    sources = []
    
    for r in results[:3]:
        if r['snippet'] and len(r['snippet']) > 20:
            snippets.append(r['snippet'])
            sources.append({'title': r['title'], 'link': r['link']})
    
    # Пытаемся прочитать страницы для получения более полного ответа
    full_context = []
    for r in results[:3]:
        text = fetch_page_text(r['link'])
        if text and len(text) > 100:
            full_context.append(text)
            # Если ещё нет источника, добавляем
            if not any(s['link'] == r['link'] for s in sources):
                sources.append({'title': r['title'], 'link': r['link']})
    
    # Формируем ответ
    answer = ""
    
    if full_context:
        # Если есть полный контекст, ищем в нём
        combined = " ".join(full_context)
        answer = extract_relevant_text(query, combined)
    
    # Если ответ не найден или слишком короткий, используем сниппеты
    if not answer or len(answer) < 30:
        if snippets:
            # Берём самый длинный сниппет
            best_snippet = max(snippets, key=len)
            answer = f"📌 {best_snippet}"
            if not sources:
                sources = [{'title': r['title'], 'link': r['link']} for r in results[:2]]
        else:
            answer = "📌 Не удалось найти подробную информацию. Попробуйте задать вопрос по-другому."
    
    # Если всё ещё нет источников, добавляем первый результат
    if not sources and results:
        sources = [{'title': results[0]['title'], 'link': results[0]['link']}]
    
    return {
        'answer': answer,
        'sources': sources
    }

def extract_relevant_text(query: str, context: str) -> str:
    """Извлекает релевантный текст из контекста"""
    if not context:
        return ""
    
    # Разбиваем на предложения
    sentences = re.split(r'[.!?…]+', context)
    
    # Извлекаем ключевые слова
    query_words = {w.lower() for w in query.split() if len(w) > 2}
    query_words -= {'это', 'как', 'что', 'кто', 'где', 'когда', 'почему', 'зачем', 'про'}
    
    scored = []
    for sent in sentences:
        sent = sent.strip()
        if len(sent) < 15:
            continue
        sent_lower = sent.lower()
        matches = sum(1 for w in query_words if w in sent_lower)
        if matches > 0:
            # Чем больше совпадений и короче предложение, тем лучше
            score = matches / (1 + len(sent.split()) / 20)
            scored.append((score, sent))
    
    scored.sort(reverse=True)
    
    if scored:
        # Берём топ-2 предложения
        result = ". ".join([s for _, s in scored[:2]])
        return result
    
    # Если совпадений нет, возвращаем первые 300 символов
    return context[:300] + "..."

def ask_with_search(query: str) -> dict:
    """Основная функция"""
    # Поиск
    results = duckduckgo_search(query)
    
    if not results:
        return {
            'answer': '❌ Не удалось найти информацию. Попробуйте переформулировать вопрос.',
            'sources': []
        }
    
    # Находим лучший ответ
    result = find_best_answer(query, results)
    
    return result

# ==================== ВЕБ-ИНТЕРФЕЙС ====================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/ask', methods=['POST'])
def ask():
    data = request.json
    question = data.get('question', '').strip()
    
    if not question:
        return jsonify({'error': 'Введите вопрос'})
    
    if len(question) < 2:
        return jsonify({'error': 'Слишком короткий вопрос'})
    
    result = ask_with_search(question)
    return jsonify(result)

@app.errorhandler(500)
def internal_error(e):
    return jsonify({'error': 'Внутренняя ошибка сервера'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("=" * 50)
    print("🦆 ИИ-помощник с интернетом")
    print("=" * 50)
    print(f"🌐 http://0.0.0.0:{port}")
    print("=" * 50)
    app.run(host='0.0.0.0', port=port, debug=False)
