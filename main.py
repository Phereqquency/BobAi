from flask import Flask, render_template, request, jsonify
from ddgs import DDGS
import requests
from bs4 import BeautifulSoup
import re
import time
import os
import random

app = Flask(__name__)

# Список пользовательских агентов для обхода блокировок
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
]

def get_random_headers():
    """Возвращает случайные заголовки для обхода блокировок"""
    return {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Cache-Control': 'max-age=0',
    }

def duckduckgo_search(query: str, num_results: int = 5):
    results = []
    try:
        print(f"🔍 Ищем: {query}")
        with DDGS() as ddgs:
            # Пробуем без региона для большего количества результатов
            for result in ddgs.text(query, max_results=num_results):
                title = result.get('title', '')
                body = result.get('body', '')
                # Проверяем наличие русских букв
                if re.search('[а-яА-Я]', title) or re.search('[а-яА-Я]', body):
                    results.append({
                        'title': title.strip(),
                        'link': result.get('href', ''),
                        'snippet': body.strip()
                    })
        
        # Если русскоязычных результатов мало, берём все
        if len(results) < 2:
            print("⚠️ Мало русскоязычных результатов, берём все")
            with DDGS() as ddgs:
                for result in ddgs.text(query, max_results=num_results):
                    if len(results) >= num_results:
                        break
                    if result.get('href') and not any(r['link'] == result.get('href') for r in results):
                        results.append({
                            'title': result.get('title', '').strip(),
                            'link': result.get('href', ''),
                            'snippet': result.get('body', '').strip()
                        })
        
        print(f"✅ Найдено результатов: {len(results)}")
        return results
    except Exception as e:
        print(f"❌ Ошибка поиска: {e}")
        return []

def fetch_page_text(url: str, max_chars: int = 4000):
    """Улучшенное чтение страниц с обходом блокировок"""
    if not url or not url.startswith('http'):
        return ""
    
    try:
        time.sleep(random.uniform(1.0, 2.0))  # Случайная задержка
        
        headers = get_random_headers()
        session = requests.Session()
        
        # Первый запрос — получаем страницу
        response = session.get(url, headers=headers, timeout=20, allow_redirects=True)
        response.raise_for_status()
        
        # Проверяем, не заблокировали ли нас
        if 'captcha' in response.text.lower() or 'access denied' in response.text.lower():
            print(f"⚠️ Похоже на блокировку: {url[:50]}...")
            return ""
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Удаляем ненужные элементы
        for element in soup.find_all(['script', 'style', 'nav', 'footer', 'header', 'aside']):
            element.decompose()
        
        # Ищем основной контент
        main_content = soup.find('main') or soup.find('article') or soup.find('div', class_=re.compile(r'content|main|post|article'))
        
        if main_content:
            text = main_content.get_text(separator=' ', strip=True)
        else:
            text = soup.get_text(separator=' ', strip=True)
        
        # Очищаем текст
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'[©™®]', '', text)  # Убираем спецсимволы
        text = re.sub(r'\b[a-zA-Z]{30,}\b', '', text)  # Убираем длинные бесполезные строки
        
        # Проверяем, есть ли русский текст
        if not re.search('[а-яА-Я]', text):
            print(f"⚠️ Нет русского текста на {url[:50]}...")
            return ""
        
        if len(text) > max_chars:
            text = text[:max_chars] + "..."
        
        return text.strip()
        
    except requests.exceptions.HTTPError as e:
        print(f"HTTP ошибка {url[:50]}: {e}")
        return ""
    except requests.exceptions.Timeout:
        print(f"⏱️ Таймаут: {url[:50]}...")
        return ""
    except Exception as e:
        print(f"❌ Ошибка чтения {url[:50]}: {e}")
        return ""

def find_relevant_text(query: str, context: str) -> str:
    """Находит наиболее релевантный текст в контексте"""
    if not context or len(context) < 50:
        return "Недостаточно информации для ответа."
    
    # Разбиваем на предложения
    sentences = re.split(r'[.!?]+', context)
    
    # Извлекаем ключевые слова из запроса
    query_words = {w.lower() for w in query.split() if len(w) > 2}
    query_words -= {'это', 'как', 'что', 'кто', 'где', 'когда', 'почему', 'зачем', 'чей', 'чья'}
    
    scored = []
    for sent in sentences:
        sent = sent.strip()
        if len(sent) < 15:
            continue
        
        sent_lower = sent.lower()
        matches = sum(1 for w in query_words if w in sent_lower)
        
        if matches > 0:
            # Чем больше совпадений и короче предложение, тем выше рейтинг
            score = matches / (1 + len(sent.split()) / 30)
            scored.append((score, sent))
    
    scored.sort(reverse=True)
    
    if scored:
        # Берём топ-3 предложения
        result = ". ".join([s for _, s in scored[:3]])
        return result
    else:
        # Если совпадений нет, возвращаем первые 300 символов
        return context[:300] + "..."

def ask_with_search(query: str) -> dict:
    """Основная функция обработки запроса"""
    # Поиск в интернете
    results = duckduckgo_search(query, num_results=5)
    
    if not results:
        return {
            'answer': '❌ Не удалось найти информацию по вашему запросу. Попробуйте переформулировать вопрос.',
            'sources': []
        }
    
    context_parts = []
    sources = []
    
    # Читаем содержимое страниц
    for r in results[:4]:  # Пробуем прочитать до 4 страниц
        link = r['link']
        if not link:
            continue
            
        text = fetch_page_text(link)
        if text and len(text) > 100:
            context_parts.append(text)
            sources.append({
                'title': r['title'][:60] if r['title'] else 'Источник',
                'link': link
            })
            # Если набрали достаточно контекста, останавливаемся
            if len(' '.join(context_parts)) > 2000:
                break
    
    if not context_parts:
        return {
            'answer': '❌ Нашлись результаты, но не удалось прочитать содержимое страниц. Попробуйте другой вопрос.',
            'sources': sources
        }
    
    # Находим ответ
    answer = find_relevant_text(query, ' '.join(context_parts))
    
    # Если ответ слишком короткий, даём подсказку
    if len(answer) < 50:
        answer += "\n\n💡 Попробуйте задать вопрос более конкретно."
    
    return {
        'answer': answer,
        'sources': sources
    }

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
    
    # Проверка на слишком короткий запрос
    if len(question) < 3:
        return jsonify({'error': 'Слишком короткий вопрос. Напишите подробнее.'})
    
    result = ask_with_search(question)
    return jsonify(result)

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Страница не найдена'}), 404

@app.errorhandler(500)
def internal_error(e):
    return jsonify({'error': 'Внутренняя ошибка сервера'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("=" * 50)
    print("🦆 ИИ-помощник с доступом в интернет")
    print("=" * 50)
    print(f"🌐 http://0.0.0.0:{port}")
    print("💡 Нажмите Ctrl+C для остановки")
    print("=" * 50)
    app.run(host='0.0.0.0', port=port, debug=False)
