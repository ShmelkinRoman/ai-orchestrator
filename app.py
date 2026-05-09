from flask import Flask, jsonify

app = Flask(__name__)


@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({"status": "ok"})

# ... rest of the code ...
