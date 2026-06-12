import os
import re
import json
import uuid
import time
import html
from datetime import datetime, timedelta
from collections import defaultdict
from flask import Flask, render_template, request, jsonify, send_file, session, redirect, url_for, Response

from captcha_generator import CaptchaGenerator

app = Flask(__name__)
app.secret_key = 'captcha-demo-secret-key-2024'

DATA_FILE = 'captcha_data.json'
MAX_RECORDS = 1000

captcha_gen = CaptchaGenerator()


def sanitize_text(text):
    if not text:
        return ''
    text = html.escape(str(text).strip())
    return text


def is_valid_captcha_text(text):
    if not text:
        return False
    return bool(re.match(r'^[A-Za-z0-9]{3,8}$', text))


class DataStore:
    def __init__(self):
        self.data = {
            'submissions': [],
            'corrections': [],
            'captcha_stats': defaultdict(lambda: {'correct': 0, 'wrong': 0, 'total': 0}),
            'sessions': {},
            'annotations': []
        }
        self.load()

    def load(self):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    self.data['submissions'] = loaded.get('submissions', [])
                    self.data['corrections'] = loaded.get('corrections', [])
                    self.data['annotations'] = loaded.get('annotations', [])
                    stats = loaded.get('captcha_stats', {})
                    for k, v in stats.items():
                        self.data['captcha_stats'][k] = v
            except Exception as e:
                print(f"Load data error: {e}")

    def save(self):
        try:
            save_data = {
                'submissions': self.data['submissions'],
                'corrections': self.data['corrections'],
                'annotations': self.data['annotations'],
                'captcha_stats': dict(self.data['captcha_stats'])
            }
            with open(DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Save data error: {e}")

    def add_submission(self, captcha_text, user_input, is_correct, ip=None):
        captcha_text = sanitize_text(captcha_text)
        user_input = sanitize_text(user_input)
        record = {
            'id': str(uuid.uuid4())[:8],
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'captcha_text': captcha_text.upper(),
            'user_input': user_input.upper() if user_input else '',
            'is_correct': is_correct,
            'ip': sanitize_text(ip) if ip else ''
        }
        self.data['submissions'].insert(0, record)
        if len(self.data['submissions']) > MAX_RECORDS:
            self.data['submissions'] = self.data['submissions'][:MAX_RECORDS]

        key = captcha_text.upper()
        self.data['captcha_stats'][key]['total'] += 1
        if is_correct:
            self.data['captcha_stats'][key]['correct'] += 1
        else:
            self.data['captcha_stats'][key]['wrong'] += 1

        self.save()
        return record

    def filter_submissions(self, result_filter='all', text_filter='', date_from='', date_to=''):
        results = self.data['submissions']
        
        if result_filter == 'correct':
            results = [r for r in results if r['is_correct']]
        elif result_filter == 'wrong':
            results = [r for r in results if not r['is_correct']]
        
        if text_filter:
            tf = text_filter.upper()
            results = [r for r in results if tf in r['captcha_text'].upper() or tf in r['user_input'].upper()]
        
        if date_from:
            try:
                df = datetime.strptime(date_from, '%Y-%m-%d')
                results = [r for r in results if datetime.strptime(r['timestamp'], '%Y-%m-%d %H:%M:%S') >= df]
            except:
                pass
        
        if date_to:
            try:
                dt = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
                results = [r for r in results if datetime.strptime(r['timestamp'], '%Y-%m-%d %H:%M:%S') < dt]
            except:
                pass
        
        return results

    def add_correction(self, original_text, correct_text, ip=None):
        original_text = sanitize_text(original_text)
        correct_text = sanitize_text(correct_text)
        
        if not is_valid_captcha_text(original_text) or not is_valid_captcha_text(correct_text):
            return None
        
        record = {
            'id': str(uuid.uuid4())[:8],
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'original_text': original_text.upper(),
            'correct_text': correct_text.upper(),
            'ip': sanitize_text(ip) if ip else '',
            'used_for_mutation': False
        }
        self.data['corrections'].insert(0, record)
        self.save()
        self.update_mutation_corpus()
        return record

    def delete_correction(self, correction_id):
        before = len(self.data['corrections'])
        self.data['corrections'] = [c for c in self.data['corrections'] if c['id'] != correction_id]
        if len(self.data['corrections']) < before:
            self.save()
            self.update_mutation_corpus()
            return True
        return False

    def get_corrections(self):
        return self.data['corrections']

    def add_annotation(self, captcha_text, label, source='manual'):
        captcha_text = sanitize_text(captcha_text)
        label = sanitize_text(label)
        record = {
            'id': str(uuid.uuid4())[:8],
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'captcha_text': captcha_text.upper(),
            'label': label.upper(),
            'is_correct': captcha_text.upper() == label.upper(),
            'source': source
        }
        self.data['annotations'].insert(0, record)
        self.save()
        return record

    def get_annotations(self, limit=200):
        return self.data['annotations'][:limit]

    def get_recent_submissions(self, limit=100):
        return self.data['submissions'][:limit]

    def get_captcha_stats(self, limit=50):
        items = sorted(
            self.data['captcha_stats'].items(),
            key=lambda x: x[1]['total'],
            reverse=True
        )
        result = []
        for text, stats in items[:limit]:
            accuracy = (stats['correct'] / stats['total'] * 100) if stats['total'] > 0 else 0
            result.append({
                'text': text,
                'correct': stats['correct'],
                'wrong': stats['wrong'],
                'total': stats['total'],
                'accuracy': round(accuracy, 1)
            })
        return result

    def get_correction_texts(self):
        return [c['correct_text'] for c in self.data['corrections'] if c.get('correct_text') and is_valid_captcha_text(c.get('correct_text'))]

    def update_mutation_corpus(self):
        corpus = self.get_correction_texts()
        captcha_gen.set_mutation_corpus(corpus)

    def get_summary(self):
        total_submissions = len(self.data['submissions'])
        correct_count = sum(1 for s in self.data['submissions'] if s['is_correct'])
        wrong_count = total_submissions - correct_count
        accuracy = (correct_count / total_submissions * 100) if total_submissions > 0 else 0
        
        total_annotations = len(self.data['annotations'])
        correct_annotations = sum(1 for a in self.data['annotations'] if a['is_correct'])
        annotation_accuracy = (correct_annotations / total_annotations * 100) if total_annotations > 0 else 0
        
        return {
            'total_submissions': total_submissions,
            'correct_count': correct_count,
            'wrong_count': wrong_count,
            'accuracy': round(accuracy, 1),
            'total_corrections': len(self.data['corrections']),
            'unique_captchas': len(self.data['captcha_stats']),
            'total_annotations': total_annotations,
            'correct_annotations': correct_annotations,
            'annotation_accuracy': round(annotation_accuracy, 1)
        }

    def get_accuracy_trend(self, points=10):
        if len(self.data['submissions']) == 0:
            return []
        
        chunk_size = max(1, len(self.data['submissions']) // points)
        trend = []
        submissions = list(reversed(self.data['submissions']))
        
        for i in range(0, len(submissions), chunk_size):
            chunk = submissions[i:i + chunk_size]
            if not chunk:
                continue
            correct = sum(1 for s in chunk if s['is_correct'])
            acc = (correct / len(chunk) * 100) if chunk else 0
            trend.append({
                'label': f'{len(chunk)} 条',
                'accuracy': round(acc, 1),
                'count': len(chunk)
            })
        
        return trend[-points:]

    def store_session_captcha(self, session_id, captcha_text):
        self.data['sessions'][session_id] = {
            'text': captcha_text.upper(),
            'created_at': time.time(),
            'verified': False
        }

    def get_session_captcha(self, session_id):
        data = self.data['sessions'].get(session_id)
        if data and (time.time() - data['created_at']) < 300 and not data.get('verified'):
            return data['text']
        return None

    def mark_session_verified(self, session_id):
        if session_id in self.data['sessions']:
            self.data['sessions'][session_id]['verified'] = True

    def clear_session_captcha(self, session_id):
        if session_id in self.data['sessions']:
            del self.data['sessions'][session_id]

    def export_data(self):
        return {
            'export_version': 1,
            'exported_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'submissions': self.data['submissions'],
            'corrections': self.data['corrections'],
            'annotations': self.data['annotations'],
            'captcha_stats': dict(self.data['captcha_stats'])
        }

    def import_data(self, import_obj, merge=True):
        if not isinstance(import_obj, dict):
            return {'success': False, 'message': '无效的导入数据格式'}

        imported_submissions = import_obj.get('submissions', [])
        imported_corrections = import_obj.get('corrections', [])
        imported_annotations = import_obj.get('annotations', [])
        imported_stats = import_obj.get('captcha_stats', {})

        if not isinstance(imported_submissions, list):
            imported_submissions = []
        if not isinstance(imported_corrections, list):
            imported_corrections = []
        if not isinstance(imported_annotations, list):
            imported_annotations = []
        if not isinstance(imported_stats, dict):
            imported_stats = {}

        stats_before = len(self.data['submissions'])

        if merge:
            existing_ids = {s['id'] for s in self.data['submissions']}
            for s in imported_submissions:
                if isinstance(s, dict) and s.get('id') and s.get('id') not in existing_ids:
                    self.data['submissions'].append(s)
                    existing_ids.add(s.get('id'))
            
            existing_corr_ids = {c['id'] for c in self.data['corrections']}
            for c in imported_corrections:
                if isinstance(c, dict) and c.get('id') and c.get('id') not in existing_corr_ids:
                    self.data['corrections'].append(c)
                    existing_corr_ids.add(c.get('id'))
            
            existing_ann_ids = {a['id'] for a in self.data['annotations']}
            for a in imported_annotations:
                if isinstance(a, dict) and a.get('id') and a.get('id') not in existing_ann_ids:
                    self.data['annotations'].append(a)
                    existing_ann_ids.add(a.get('id'))
            
            for text, st in imported_stats.items():
                if isinstance(st, dict):
                    cur = self.data['captcha_stats'][text]
                    cur['correct'] = cur.get('correct', 0) + st.get('correct', 0)
                    cur['wrong'] = cur.get('wrong', 0) + st.get('wrong', 0)
                    cur['total'] = cur.get('total', 0) + st.get('total', 0)
        else:
            self.data['submissions'] = imported_submissions
            self.data['corrections'] = imported_corrections
            self.data['annotations'] = imported_annotations
            self.data['captcha_stats'] = defaultdict(lambda: {'correct': 0, 'wrong': 0, 'total': 0})
            for text, st in imported_stats.items():
                if isinstance(st, dict):
                    self.data['captcha_stats'][text] = {
                        'correct': st.get('correct', 0),
                        'wrong': st.get('wrong', 0),
                        'total': st.get('total', 0)
                    }

        self.data['submissions'].sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        self.data['corrections'].sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        self.data['annotations'].sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        
        self.save()
        self.update_mutation_corpus()

        return {
            'success': True,
            'imported_submissions': len(imported_submissions),
            'imported_corrections': len(imported_corrections),
            'imported_annotations': len(imported_annotations),
            'total_submissions_after': len(self.data['submissions'])
        }


store = DataStore()
store.update_mutation_corpus()


@app.route('/')
def index():
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
    return render_template('index.html')


@app.route('/captcha/image')
def get_captcha_image():
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
    
    difficulty = request.args.get('difficulty', 'normal')
    captcha_gen.set_difficulty(difficulty)
    
    buffer, text = captcha_gen.generate_image()
    store.store_session_captcha(session['session_id'], text)
    
    return send_file(buffer, mimetype='image/png')


@app.route('/captcha/verify', methods=['POST'])
def verify_captcha():
    data = request.get_json() or request.form
    user_input = data.get('captcha', '').strip()
    
    session_id = session.get('session_id')
    if not session_id:
        return jsonify({'success': False, 'error_code': 'session_expired', 'message': '会话已过期，请刷新页面', 'show_correction': False}), 400
    
    correct_text = store.get_session_captcha(session_id)
    if not correct_text:
        return jsonify({'success': False, 'error_code': 'captcha_expired', 'message': '验证码已过期或已使用，请刷新', 'show_correction': False}), 400
    
    is_correct = user_input.upper() == correct_text.upper()
    ip = request.remote_addr
    
    store.add_submission(correct_text, user_input, is_correct, ip)
    store.mark_session_verified(session_id)
    
    return jsonify({
        'success': True,
        'is_correct': is_correct,
        'correct_text': correct_text if not is_correct else None,
        'show_correction': not is_correct,
        'message': '验证成功！' if is_correct else '验证失败'
    })


@app.route('/captcha/correct', methods=['POST'])
def submit_correction():
    data = request.get_json() or request.form
    original_text = data.get('original_text', '').strip()
    correct_text = data.get('correct_text', '').strip()
    
    if not original_text or not correct_text:
        return jsonify({'success': False, 'message': '请提供完整信息'}), 400
    
    if not is_valid_captcha_text(original_text) or not is_valid_captcha_text(correct_text):
        return jsonify({'success': False, 'message': '验证码格式无效，仅支持3-8位字母和数字'}), 400
    
    if original_text.upper() == correct_text.upper():
        return jsonify({'success': False, 'message': '纠错内容与原始内容相同，无需提交'}), 400
    
    ip = request.remote_addr
    record = store.add_correction(original_text, correct_text, ip)
    
    if not record:
        return jsonify({'success': False, 'message': '提交失败，数据格式校验未通过'}), 400
    
    return jsonify({
        'success': True,
        'message': '纠错已提交，感谢您的反馈！',
        'record': record
    })


@app.route('/admin')
def admin_panel():
    return render_template('admin.html')


@app.route('/samples')
def samples_page():
    return render_template('samples.html')


@app.route('/training')
def training_page():
    return render_template('training.html')


@app.route('/api/stats')
def api_stats():
    summary = store.get_summary()
    submissions = store.get_recent_submissions(100)
    captcha_stats = store.get_captcha_stats(50)
    
    return jsonify({
        'summary': summary,
        'submissions': submissions,
        'captcha_stats': captcha_stats
    })


@app.route('/api/submissions/filter', methods=['GET', 'POST'])
def api_filter_submissions():
    data = request.get_json() or request.args
    result_filter = data.get('result_filter', 'all')
    text_filter = data.get('text_filter', '').strip()
    date_from = data.get('date_from', '').strip()
    date_to = data.get('date_to', '').strip()
    limit = int(data.get('limit', 200))
    
    results = store.filter_submissions(result_filter, text_filter, date_from, date_to)
    results = results[:limit]
    
    return jsonify({
        'success': True,
        'count': len(results),
        'submissions': results
    })


@app.route('/api/difficulty', methods=['POST'])
def set_difficulty():
    data = request.get_json() or request.form
    difficulty = data.get('difficulty', 'normal')
    if difficulty not in ['normal', 'hard']:
        return jsonify({'success': False, 'message': '无效的难度级别'}), 400
    captcha_gen.set_difficulty(difficulty)
    return jsonify({'success': True, 'difficulty': difficulty})


@app.route('/api/captcha', methods=['GET'])
def api_get_captcha():
    difficulty = request.args.get('difficulty', 'normal')
    captcha_gen.set_difficulty(difficulty)
    
    api_key = request.headers.get('X-API-Key', 'demo')
    session_id = f"api_{api_key}_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    
    buffer, text = captcha_gen.generate_image()
    store.store_session_captcha(session_id, text)
    
    return jsonify({
        'success': True,
        'session_id': session_id,
        'captcha_text': text,
        'image_data': buffer.getvalue().hex(),
        'expires_at': int(time.time() + 300)
    })


@app.route('/api/captcha/<session_id>/verify', methods=['POST'])
def api_verify_captcha(session_id):
    data = request.get_json() or request.form
    user_input = data.get('captcha', '').strip()
    
    correct_text = store.get_session_captcha(session_id)
    if not correct_text:
        return jsonify({'success': False, 'error_code': 'captcha_expired', 'message': '验证码已过期或不存在', 'show_correction': False}), 404
    
    is_correct = user_input.upper() == correct_text.upper()
    ip = request.remote_addr
    
    store.add_submission(correct_text, user_input, is_correct, ip)
    store.mark_session_verified(session_id)
    
    return jsonify({
        'success': True,
        'is_correct': is_correct,
        'correct_text': correct_text,
        'show_correction': not is_correct
    })


@app.route('/api/corrections')
def api_corrections():
    corrections = store.get_corrections()
    return jsonify({
        'success': True,
        'corrections': corrections,
        'corpus': store.get_correction_texts(),
        'count': len(corrections)
    })


@app.route('/api/corrections/<correction_id>', methods=['DELETE'])
def api_delete_correction(correction_id):
    result = store.delete_correction(correction_id)
    if result:
        return jsonify({'success': True, 'message': '已删除该纠错记录'})
    return jsonify({'success': False, 'message': '未找到该记录'}), 404


@app.route('/api/generate_from_corrections', methods=['POST'])
def generate_from_corrections():
    data = request.get_json() or request.form
    count = int(data.get('count', 5))
    count = min(max(count, 1), 20)
    
    corpus = store.get_correction_texts()
    if not corpus:
        return jsonify({'success': False, 'message': '暂无纠错数据可用'}), 400
    
    captcha_gen.set_mutation_corpus(corpus)
    captcha_gen.set_difficulty('hard')
    
    samples = []
    for _ in range(count):
        buffer, text = captcha_gen.generate_image()
        samples.append({
            'id': str(uuid.uuid4())[:8],
            'text': text,
            'image_data': buffer.getvalue().hex()
        })
    
    return jsonify({
        'success': True,
        'samples': samples,
        'corpus_size': len(corpus)
    })


@app.route('/api/generate_correction_preview', methods=['POST'])
def generate_correction_preview():
    data = request.get_json() or request.form
    original_text = data.get('original_text', '').strip()
    correct_text = data.get('correct_text', '').strip()
    
    if not is_valid_captcha_text(original_text) or not is_valid_captcha_text(correct_text):
        return jsonify({'success': False, 'message': '无效的验证码文本'}), 400
    
    buffer_orig, _ = captcha_gen.generate_image(original_text)
    buffer_corr, _ = captcha_gen.generate_image(correct_text)
    
    captcha_gen.set_difficulty('hard')
    mutations = []
    for _ in range(3):
        buf, txt = captcha_gen.generate_image()
        mutations.append({
            'text': txt,
            'image_data': buf.getvalue().hex()
        })
    captcha_gen.set_difficulty('normal')
    
    return jsonify({
        'success': True,
        'original': {
            'text': original_text.upper(),
            'image_data': buffer_orig.getvalue().hex()
        },
        'correction': {
            'text': correct_text.upper(),
            'image_data': buffer_corr.getvalue().hex()
        },
        'mutations': mutations
    })


@app.route('/api/data/export')
def api_export_data():
    export_obj = store.export_data()
    json_str = json.dumps(export_obj, ensure_ascii=False, indent=2)
    
    filename = f"captcha_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    return Response(
        json_str,
        mimetype='application/json',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


@app.route('/api/data/import', methods=['POST'])
def api_import_data():
    if 'file' in request.files:
        file = request.files['file']
        try:
            content = file.read().decode('utf-8')
            import_obj = json.loads(content)
        except Exception as e:
            return jsonify({'success': False, 'message': f'文件解析失败: {str(e)}'}), 400
    else:
        import_obj = request.get_json(silent=True)
        if not import_obj:
            return jsonify({'success': False, 'message': '请提供导入数据或文件'}), 400
    
    merge = request.args.get('merge', 'true').lower() != 'false'
    if request.form.get('merge'):
        merge = request.form.get('merge').lower() != 'false'
    
    result = store.import_data(import_obj, merge=merge)
    if result['success']:
        return jsonify(result)
    return jsonify(result), 400


@app.route('/api/annotations', methods=['GET'])
def api_get_annotations():
    limit = int(request.args.get('limit', 200))
    return jsonify({
        'success': True,
        'annotations': store.get_annotations(limit),
        'count': len(store.get_annotations(limit))
    })


@app.route('/api/annotations', methods=['POST'])
def api_add_annotation():
    data = request.get_json() or request.form
    captcha_text = data.get('captcha_text', '').strip()
    label = data.get('label', '').strip()
    source = data.get('source', 'manual')
    
    if not is_valid_captcha_text(captcha_text) or not is_valid_captcha_text(label):
        return jsonify({'success': False, 'message': '验证码格式无效'}), 400
    
    record = store.add_annotation(captcha_text, label, source)
    return jsonify({
        'success': True,
        'record': record
    })


@app.route('/api/training/samples', methods=['GET'])
def api_training_samples():
    count = int(request.args.get('count', 6))
    count = min(max(count, 1), 12)
    difficulty = request.args.get('difficulty', 'auto')
    
    if difficulty == 'auto':
        summary = store.get_summary()
        acc = summary.get('accuracy', 0)
        if acc >= 80:
            captcha_gen.set_difficulty('hard')
        elif acc <= 40:
            captcha_gen.set_difficulty('normal')
        else:
            captcha_gen.set_difficulty(random.choice(['normal', 'hard']))
    else:
        captcha_gen.set_difficulty(difficulty)
    
    samples = []
    for _ in range(count):
        buffer, text = captcha_gen.generate_image()
        samples.append({
            'id': str(uuid.uuid4())[:8],
            'captcha_text': text,
            'image_data': buffer.getvalue().hex()
        })
    
    return jsonify({
        'success': True,
        'samples': samples,
        'difficulty': captcha_gen.difficulty
    })


@app.route('/api/training/suggestion')
def api_training_suggestion():
    summary = store.get_summary()
    trend = store.get_accuracy_trend(8)
    
    accuracy = summary.get('accuracy', 0)
    total = summary.get('total_submissions', 0)
    
    suggestion = {
        'recommended_difficulty': 'normal',
        'reason': '',
        'accuracy': accuracy,
        'total_submissions': total,
        'trend': trend,
        'next_steps': []
    }
    
    if total < 20:
        suggestion['reason'] = '样本量不足，建议先积累更多标注数据'
        suggestion['recommended_difficulty'] = 'normal'
        suggestion['next_steps'] = [
            '继续在普通模式下收集基础样本',
            '建议至少收集50条记录再调整难度'
        ]
    elif accuracy >= 80:
        suggestion['reason'] = '当前识别准确率较高，建议提升难度'
        suggestion['recommended_difficulty'] = 'hard'
        suggestion['next_steps'] = [
            '切换到困难模式获取更有挑战性的样本',
            '使用纠错数据生成变异样本',
            '增加标注样本量以提高模型鲁棒性'
        ]
    elif accuracy <= 40:
        suggestion['reason'] = '当前识别准确率较低，建议降低难度或增加训练'
        suggestion['recommended_difficulty'] = 'normal'
        suggestion['next_steps'] = [
            '在普通模式下多练习熟悉验证码特征',
            '检查纠错样本库，确保标注质量',
            '可以在训练模拟区进行批量标注练习'
        ]
    else:
        suggestion['reason'] = '当前识别准确率中等，可以根据需要调整难度'
        suggestion['recommended_difficulty'] = random.choice(['normal', 'hard'])
        suggestion['next_steps'] = [
            '保持当前难度继续练习',
            '可尝试挑战困难模式',
            '定期检查准确率变化趋势'
        ]
    
    return jsonify({
        'success': True,
        'suggestion': suggestion
    })


if __name__ == '__main__':
    import random
    app.run(host='0.0.0.0', port=5000, debug=True)
