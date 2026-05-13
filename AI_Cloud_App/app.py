import os
import json
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from groq import Groq
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore

load_dotenv()

app = Flask(__name__)
CORS(app)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
client = Groq(api_key=GROQ_API_KEY)

# الاتصال بـ Firebase
try:
    firebase_cred_json = os.getenv("FIREBASE_CREDENTIALS")
    if firebase_cred_json:
        cred_dict = json.loads(firebase_cred_json)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        print("✅ تم الاتصال بـ Firebase بنجاح")
except Exception as e:
    print(f"❌ خطأ في الاتصال بـ Firebase: {e}")

@app.route('/', methods=['GET'])
def home():
    return render_template('index.html')

@app.route('/ask', methods=['POST'])
def ask_ai():
    data = request.json
    user_question = data.get("question", "").strip()
    uid = data.get("uid") # رقم المستخدم السري القادم من الواجهة

    if not user_question: return jsonify({"error": "الرجاء كتابة سؤال"}), 400
    if not uid: return jsonify({"error": "غير مصرح لك. يرجى تسجيل الدخول."}), 401

    try:
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "أنت مساعد ذكي ومفيد وتتحدث العربية بطلاقة."},
                {"role": "user", "content": user_question}
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.7,
        )
        ai_answer = response.choices[0].message.content

        # حفظ المحادثة مع رقم الـ UID الخاص بالمستخدم
        chat_document = {
            "uid": uid,
            "question": user_question,
            "answer": ai_answer,
            "timestamp": firestore.SERVER_TIMESTAMP 
        }
        db.collection("chats").add(chat_document)

        return jsonify({"answer": ai_answer})
    except Exception as e:
        return jsonify({"error": "حدث خطأ داخلي."}), 500

@app.route('/history', methods=['GET'])
def get_history():
    uid = request.args.get('uid')
    if not uid: return jsonify({"history":[]})

    try:
        # جلب المحادثات الخاصة بهذا المستخدم فقط
        chats_ref = db.collection("chats").where("uid", "==", uid).stream()
        
        chats =[]
        for doc in chats_ref:
            d = doc.to_dict()
            # ترتيب زمني
            d['time_val'] = d['timestamp'].timestamp() if d.get('timestamp') else datetime.now().timestamp()
            chats.append(d)
            
        # ترتيب المحادثات من الأقدم للأحدث (حسب الوقت)
        chats.sort(key=lambda x: x['time_val'])
        
        # أخذ آخر 15 محادثة وعرضها
        formatted_chats = [{"question": c.get("question", ""), "answer": c.get("answer", "")} for c[-15:] in [chats] for c in chats[-15:]]
        
        return jsonify({"history": formatted_chats})
    except Exception as e:
        print(e)
        return jsonify({"error": "تعذر جلب السجل"}), 500

@app.route('/track', methods=['POST'])
def track_visitor():
    try:
        ip = request.headers.getlist("X-Forwarded-For")[0] if request.headers.getlist("X-Forwarded-For") else request.remote_addr
        db.collection("visitors").add({
            "ip_address": ip,
            "device_info": request.headers.get('User-Agent'),
            "visited_at": firestore.SERVER_TIMESTAMP
        })
        return jsonify({"status": "tracked"})
    except:
        return jsonify({"error": "error"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)), debug=False)
