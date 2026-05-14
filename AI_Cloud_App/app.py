import os
import json
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from groq import Groq
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore

# تحميل المتغيرات البيئية
load_dotenv()

app = Flask(__name__)
CORS(app)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
client = Groq(api_key=GROQ_API_KEY)

# ==========================================
# الاتصال بـ Firebase
# ==========================================
try:
    firebase_cred_json = os.getenv("FIREBASE_CREDENTIALS")
    if firebase_cred_json:
        cred_dict = json.loads(firebase_cred_json)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        print("✅ تم الاتصال بـ Firebase بنجاح")
    else:
        print("⚠️ تحذير: مفاتيح Firebase غير موجودة في السحابة.")
except Exception as e:
    print(f"❌ خطأ في الاتصال بـ Firebase: {e}")

# ==========================================
# المسارات (Routes)
# ==========================================
@app.route('/', methods=['GET'])
def home():
    return render_template('index.html')

@app.route('/ask', methods=['POST'])
def ask_ai():
    data = request.json
    user_question = data.get("question", "").strip()
    image_url = data.get("image_url", "")
    uid = data.get("uid")

    if not user_question and not image_url: 
        return jsonify({"error": "الرجاء كتابة سؤال أو رفع صورة"}), 400
    if not uid: 
        return jsonify({"error": "غير مصرح لك. يرجى تسجيل الدخول."}), 401

    # تجهيز رسالة النظام بناءً على وجود صورة أم لا
    messages = [{"role": "system", "content": "أنت مساعد ذكي ومفيد وتتحدث العربية بطلاقة."}]
    
    if image_url:
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": user_question if user_question else "اشرح ما في هذه الصورة بالتفصيل."},
                {"type": "image_url", "image_url": {"url": image_url}}
            ]
        })
        model_name = "meta-llama/llama-4-scout-17b-16e-instruct" # 👈 أحدث نموذج رؤية من Groq 
    else:
        messages.append({"role": "user", "content": user_question})
        model_name = "llama-3.3-70b-versatile" # النموذج القوي للنصوص

    try:
        response = client.chat.completions.create(
            messages=messages,
            model=model_name,
            temperature=0.7,
        )
        ai_answer = response.choices[0].message.content

        # حفظ المحادثة
        chat_document = {
            "uid": uid,
            "question": user_question,
            "answer": ai_answer,
            "image_url": image_url,
            "timestamp": firestore.SERVER_TIMESTAMP 
        }
        db.collection("chats").add(chat_document)

        return jsonify({"answer": ai_answer})
        
    except Exception as e:
        print(f"❌ خطأ في معالجة الذكاء الاصطناعي: {str(e)}")
        return jsonify({"error": f"حدث خطأ في معالجة الذكاء الاصطناعي: {str(e)}"}), 500

@app.route('/history', methods=['GET'])
def get_history():
    uid = request.args.get('uid')
    if not uid: 
        return jsonify({"history": []})

    try:
        chats_ref = db.collection("chats").where("uid", "==", uid).stream()
        chats = []
        for doc in chats_ref:
            d = doc.to_dict()
            d['time_val'] = d['timestamp'].timestamp() if d.get('timestamp') else datetime.now().timestamp()
            chats.append(d)
            
        chats.sort(key=lambda x: x['time_val'])
        
        formatted_chats = [
            {
                "question": c.get("question", ""), 
                "answer": c.get("answer", ""), 
                "image_url": c.get("image_url", "")
            } for c in chats[-15:]
        ]
        
        return jsonify({"history": formatted_chats})
    except Exception as e:
        print(f"❌ خطأ في جلب السجل: {e}")
        return jsonify({"error": "تعذر جلب السجل"}), 500

@app.route('/track', methods=['POST'])
def track_visitor():
    try:
        if request.headers.getlist("X-Forwarded-For"):
            ip = request.headers.getlist("X-Forwarded-For")[0]
        else:
            ip = request.remote_addr
            
        db.collection("visitors").add({
            "ip_address": ip,
            "device_info": request.headers.get('User-Agent'),
            "visited_at": firestore.SERVER_TIMESTAMP
        })
        return jsonify({"status": "tracked"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)), debug=False)
