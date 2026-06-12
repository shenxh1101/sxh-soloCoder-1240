import os
import re
import json
import uuid
import time
import html
import random
from datetime import datetime, timedelta
from collections import defaultdict, Counter
from flask import Flask, render_template, request, jsonify, send_file, session, redirect, url_for, Response

from captcha_generator import CaptchaGenerator

app = Flask(__name__)
app.secret_key = 'captcha-demo-secret-key-2024'

DATA_FILE = 'captcha_data.json'
MAX_RECORDS = 2000

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


def recalc_captcha_stats(submissions):
    stats = defaultdict(lambda: {'correct': 0, 'wrong': 0, 'total': 0})
    for s in submissions:
        key = str(s.get('captcha_text', '')).upper()
        if not key:
            continue
        stats[key]['total'] += 1
        if s.get('is_correct'):
            stats[key]['correct'] += 1
        else:
            stats[key]['wrong'] += 1
    return dict(stats)


class DataStore:
    def __init__(self):
        self.data = {
            'submissions': [],
            'corrections': [],
            'captcha_stats': defaultdict(lambda: {'correct': 0, 'wrong': 0, 'total': 0}),
            'sessions': {},
            'annotations': [],
            'mutation_batches': [],
            'training_batches': []
        }
        self.load()
        self._validate_and_repair()

    def _validate_and_repair(self):
        recalc = recalc_captcha_stats(self.data['submissions'])
        current_keys = set(self.data['captcha_stats'].keys())
        recalc_keys = set(recalc.keys())
        need_fix = False
        
        if current_keys != recalc_keys:
            need_fix = True
        else:
            for k in recalc_keys:
                c = self.data['captcha_stats'][k]
                r = recalc[k]
                if (c.get('correct', 0) != r['correct'] or
                    c.get('wrong', 0) != r['wrong'] or
                    c.get('total', 0) != r['total']):
                    need_fix = True
                    break
        
        if need_fix:
            print(f"[DataStore] 统计不一致，重新计算 captcha_stats...")
            self.data['captcha_stats'] = defaultdict(lambda: {'correct': 0, 'wrong': 0, 'total': 0})
            for k, v in recalc.items():
                self.data['captcha_stats'][k] = v
            self.save()

    def load(self):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    self.data['submissions'] = loaded.get('submissions', [])
                    self.data['corrections'] = loaded.get('corrections', [])
                    self.data['annotations'] = loaded.get('annotations', [])
                    self.data['mutation_batches'] = loaded.get('mutation_batches', [])
                    self.data['training_batches'] = loaded.get('training_batches', [])
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
                'mutation_batches': self.data['mutation_batches'],
                'training_batches': self.data['training_batches'],
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
            'is_correct': bool(is_correct),
            'ip': sanitize_text(ip) if ip else ''
        }
        self.data['submissions'].insert(0, record)
        if len(self.data['submissions']) > MAX_RECORDS:
            removed = self.data['submissions'][MAX_RECORDS:]
            self.data['submissions'] = self.data['submissions'][:MAX_RECORDS]
            for r in removed:
                key = r['captcha_text']
                self.data['captcha_stats'][key]['total'] = max(0, self.data['captcha_stats'][key]['total'] - 1)
                if r['is_correct']:
                    self.data['captcha_stats'][key]['correct'] = max(0, self.data['captcha_stats'][key]['correct'] - 1)
                else:
                    self.data['captcha_stats'][key]['wrong'] = max(0, self.data['captcha_stats'][key]['wrong'] - 1)

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
        
        if original_text.upper() == correct_text.upper():
            return None

        existing = [c for c in self.data['corrections']
                    if c.get('original_text', '').upper() == original_text.upper()
                    and c.get('correct_text', '').upper() == correct_text.upper()]
        if existing:
            return existing[0]
        
        record = {
            'id': str(uuid.uuid4())[:8],
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'original_text': original_text.upper(),
            'correct_text': correct_text.upper(),
            'ip': sanitize_text(ip) if ip else '',
            'status': 'trusted'
        }
        self.data['corrections'].insert(0, record)
        self.save()
        self.update_mutation_corpus()
        return record

    def update_correction_status(self, correction_id, status):
        if status not in ['trusted', 'suspect', 'discarded']:
            return False
        for c in self.data['corrections']:
            if c['id'] == correction_id:
                c['status'] = status
                if 'updated_at' not in c:
                    c['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                self.save()
                self.update_mutation_corpus()
                return True
        return False

    def delete_correction(self, correction_id):
        before = len(self.data['corrections'])
        self.data['corrections'] = [c for c in self.data['corrections'] if c['id'] != correction_id]
        if len(self.data['corrections']) < before:
            self.save()
            self.update_mutation_corpus()
            return True
        return False

    def get_corrections(self, status_filter='all'):
        if status_filter == 'all':
            return self.data['corrections']
        return [c for c in self.data['corrections'] if c.get('status', 'trusted') == status_filter]

    def add_mutation_batch(self, name, samples, corpus_size, source='trusted_only'):
        batch = {
            'id': 'mb_' + str(uuid.uuid4())[:8],
            'name': sanitize_text(name) or f'变异批次_{datetime.now().strftime("%Y%m%d_%H%M")}',
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'samples': samples,
            'corpus_size': corpus_size,
            'source': source,
            'count': len(samples)
        }
        self.data['mutation_batches'].insert(0, batch)
        if len(self.data['mutation_batches']) > 50:
            self.data['mutation_batches'] = self.data['mutation_batches'][:50]
        self.save()
        return batch

    def delete_mutation_batch(self, batch_id):
        before = len(self.data['mutation_batches'])
        self.data['mutation_batches'] = [b for b in self.data['mutation_batches'] if b['id'] != batch_id]
        if len(self.data['mutation_batches']) < before:
            self.save()
            return True
        return False

    def get_mutation_batches(self):
        return self.data['mutation_batches']

    def add_training_batch(self, samples_data, annotations_data, difficulty='auto'):
        correct = sum(1 for a in annotations_data if a.get('is_correct'))
        total = len(annotations_data)
        accuracy = (correct / total * 100) if total > 0 else 0

        wrong_chars = Counter()
        for a in annotations_data:
            if not a.get('is_correct'):
                expected = a.get('expected', '')
                labeled = a.get('label', '')
                for i, ch in enumerate(expected):
                    if i >= len(labeled) or labeled[i] != ch:
                        wrong_chars[ch] += 1
                if len(labeled) != len(expected):
                    for ch in labeled:
                        wrong_chars[ch] += 0

        prev_batch = self.data['training_batches'][0] if self.data['training_batches'] else None
        prev_acc = prev_batch.get('accuracy', 0) if prev_batch else 0
        delta = round(accuracy - prev_acc, 1) if prev_batch else None

        batch = {
            'id': 'tb_' + str(uuid.uuid4())[:8],
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'difficulty': difficulty,
            'total': total,
            'correct': correct,
            'wrong': total - correct,
            'accuracy': round(accuracy, 1),
            'delta': delta,
            'top_wrong_chars': wrong_chars.most_common(5),
            'details': annotations_data
        }
        self.data['training_batches'].insert(0, batch)
        if len(self.data['training_batches']) > 50:
            self.data['training_batches'] = self.data['training_batches'][:50]
        self.save()
        return batch

    def get_training_batches(self, limit=20):
        return self.data['training_batches'][:limit]

    def add_annotation(self, captcha_text, label, source='manual'):
        captcha_text = sanitize_text(captcha_text)
        label = sanitize_text(label)
        if not is_valid_captcha_text(captcha_text) or not is_valid_captcha_text(label):
            return None
        record = {
            'id': str(uuid.uuid4())[:8],
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'captcha_text': captcha_text.upper(),
            'label': label.upper(),
            'is_correct': captcha_text.upper() == label.upper(),
            'source': source
        }
        self.data['annotations'].insert(0, record)
        if len(self.data['annotations']) > MAX_RECORDS:
            self.data['annotations'] = self.data['annotations'][:MAX_RECORDS]
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

    def get_correction_texts(self, trusted_only=False):
        texts = []
        for c in self.data['corrections']:
            status = c.get('status', 'trusted')
            if status == 'discarded':
                continue
            if trusted_only and status != 'trusted':
                continue
            t = c.get('correct_text')
            if t and is_valid_captcha_text(t):
                texts.append(t)
        return texts

    def update_mutation_corpus(self):
        corpus = self.get_correction_texts(trusted_only=False)
        captcha_gen.set_mutation_corpus(corpus)

    def get_data_quality_overview(self):
        captcha_texts = defaultdict(lambda: {
            'text': '',
            'submissions': 0,
            'correct': 0,
            'wrong': 0,
            'accuracy': 0,
            'corrections': [],
            'annotations': []
        })

        for s in self.data['submissions']:
            key = s['captcha_text']
            if not key:
                continue
            captcha_texts[key]['text'] = key
            captcha_texts[key]['submissions'] += 1
            if s['is_correct']:
                captcha_texts[key]['correct'] += 1
            else:
                captcha_texts[key]['wrong'] += 1

        for c in self.data['corrections']:
            for txt in [c.get('original_text'), c.get('correct_text')]:
                if txt:
                    captcha_texts[txt]['text'] = txt
                    captcha_texts[txt]['corrections'].append({
                        'id': c.get('id'),
                        'original': c.get('original_text'),
                        'correct': c.get('correct_text'),
                        'status': c.get('status', 'trusted'),
                        'timestamp': c.get('timestamp')
                    })

        for a in self.data['annotations']:
            key = a.get('captcha_text')
            if key:
                captcha_texts[key]['text'] = key
                captcha_texts[key]['annotations'].append({
                    'id': a.get('id'),
                    'label': a.get('label'),
                    'is_correct': a.get('is_correct'),
                    'source': a.get('source'),
                    'timestamp': a.get('timestamp')
                })

        result = []
        for k, v in captcha_texts.items():
            if v['submissions'] + len(v['corrections']) + len(v['annotations']) == 0:
                continue
            acc = (v['correct'] / v['submissions'] * 100) if v['submissions'] > 0 else None
            v['accuracy'] = round(acc, 1) if acc is not None else None
            v['text'] = k
            v['trouble_score'] = (v['wrong'] * 2) + len(v['corrections']) * 3 + (len([a for a in v['annotations'] if not a['is_correct']]) * 1)
            result.append(v)

        result.sort(key=lambda x: x['trouble_score'], reverse=True)
        return result

    def get_summary(self):
        total_submissions = len(self.data['submissions'])
        correct_count = sum(1 for s in self.data['submissions'] if s['is_correct'])
        wrong_count = total_submissions - correct_count
        accuracy = (correct_count / total_submissions * 100) if total_submissions > 0 else 0
        
        total_annotations = len(self.data['annotations'])
        correct_annotations = sum(1 for a in self.data['annotations'] if a['is_correct'])
        annotation_accuracy = (correct_annotations / total_annotations * 100) if total_annotations > 0 else 0

        trusted_corrections = len([c for c in self.data['corrections'] if c.get('status', 'trusted') == 'trusted'])
        suspect_corrections = len([c for c in self.data['corrections'] if c.get('status') == 'suspect'])
        discarded_corrections = len([c for c in self.data['corrections'] if c.get('status') == 'discarded'])
        
        return {
            'total_submissions': total_submissions,
            'correct_count': correct_count,
            'wrong_count': wrong_count,
            'accuracy': round(accuracy, 1),
            'total_corrections': len(self.data['corrections']),
            'trusted_corrections': trusted_corrections,
            'suspect_corrections': suspect_corrections,
            'discarded_corrections': discarded_corrections,
            'unique_captchas': len(self.data['captcha_stats']),
            'total_annotations': total_annotations,
            'correct_annotations': correct_annotations,
            'annotation_accuracy': round(annotation_accuracy, 1),
            'mutation_batches_count': len(self.data['mutation_batches']),
            'training_batches_count': len(self.data['training_batches'])
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
        self._validate_and_repair()
        return {
            'export_version': 2,
            'exported_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'submissions': self.data['submissions'],
            'corrections': self.data['corrections'],
            'annotations': self.data['annotations'],
            'mutation_batches': self.data['mutation_batches'],
            'training_batches': self.data['training_batches'],
            'captcha_stats': dict(self.data['captcha_stats'])
        }

    def import_data(self, import_obj, merge=True):
        if not isinstance(import_obj, dict):
            return {'success': False, 'message': '无效的导入数据格式'}

        imported_submissions = import_obj.get('submissions', [])
        imported_corrections = import_obj.get('corrections', [])
        imported_annotations = import_obj.get('annotations', [])
        imported_mutation_batches = import_obj.get('mutation_batches', [])
        imported_training_batches = import_obj.get('training_batches', [])
        imported_stats = import_obj.get('captcha_stats', {})

        if not isinstance(imported_submissions, list):
            imported_submissions = []
        if not isinstance(imported_corrections, list):
            imported_corrections = []
        if not isinstance(imported_annotations, list):
            imported_annotations = []
        if not isinstance(imported_mutation_batches, list):
            imported_mutation_batches = []
        if not isinstance(imported_training_batches, list):
            imported_training_batches = []
        if not isinstance(imported_stats, dict):
            imported_stats = {}

        imported_submissions_count = 0
        imported_corrections_count = 0
        imported_annotations_count = 0
        imported_mutation_count = 0
        imported_training_count = 0

        if merge:
            existing_ids = {s['id'] for s in self.data['submissions'] if s.get('id')}
            for s in imported_submissions:
                if (isinstance(s, dict)
                        and s.get('id')
                        and s.get('captcha_text') is not None
                        and s.get('is_correct') is not None
                        and s.get('id') not in existing_ids):
                    self.data['submissions'].append(s)
                    existing_ids.add(s.get('id'))
                    imported_submissions_count += 1

            existing_corr_ids = {c['id'] for c in self.data['corrections'] if c.get('id')}
            for c in imported_corrections:
                if isinstance(c, dict) and c.get('id') and c.get('id') not in existing_corr_ids:
                    if 'status' not in c:
                        c['status'] = 'trusted'
                    self.data['corrections'].append(c)
                    existing_corr_ids.add(c.get('id'))
                    imported_corrections_count += 1

            existing_ann_ids = {a['id'] for a in self.data['annotations'] if a.get('id')}
            for a in imported_annotations:
                if isinstance(a, dict) and a.get('id') and a.get('id') not in existing_ann_ids:
                    self.data['annotations'].append(a)
                    existing_ann_ids.add(a.get('id'))
                    imported_annotations_count += 1

            existing_mb_ids = {b['id'] for b in self.data['mutation_batches'] if b.get('id')}
            for b in imported_mutation_batches:
                if isinstance(b, dict) and b.get('id') and b.get('id') not in existing_mb_ids:
                    self.data['mutation_batches'].append(b)
                    existing_mb_ids.add(b.get('id'))
                    imported_mutation_count += 1

            existing_tb_ids = {b['id'] for b in self.data['training_batches'] if b.get('id')}
            for b in imported_training_batches:
                if isinstance(b, dict) and b.get('id') and b.get('id') not in existing_tb_ids:
                    self.data['training_batches'].append(b)
                    existing_tb_ids.add(b.get('id'))
                    imported_training_count += 1
        else:
            self.data['submissions'] = [s for s in imported_submissions if isinstance(s, dict)]
            imported_submissions_count = len(self.data['submissions'])
            self.data['corrections'] = []
            for c in imported_corrections:
                if isinstance(c, dict):
                    if 'status' not in c:
                        c['status'] = 'trusted'
                    self.data['corrections'].append(c)
            imported_corrections_count = len(self.data['corrections'])
            self.data['annotations'] = [a for a in imported_annotations if isinstance(a, dict)]
            imported_annotations_count = len(self.data['annotations'])
            self.data['mutation_batches'] = [b for b in imported_mutation_batches if isinstance(b, dict)]
            imported_mutation_count = len(self.data['mutation_batches'])
            self.data['training_batches'] = [b for b in imported_training_batches if isinstance(b, dict)]
            imported_training_count = len(self.data['training_batches'])

        new_stats = recalc_captcha_stats(self.data['submissions'])
        self.data['captcha_stats'] = defaultdict(lambda: {'correct': 0, 'wrong': 0, 'total': 0})
        for k, v in new_stats.items():
            self.data['captcha_stats'][k] = v

        self.data['submissions'].sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        self.data['corrections'].sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        self.data['annotations'].sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        self.data['mutation_batches'].sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        self.data['training_batches'].sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        
        self.save()
        self.update_mutation_corpus()

        return {
            'success': True,
            'imported_submissions': imported_submissions_count,
            'imported_corrections': imported_corrections_count,
            'imported_annotations': imported_annotations_count,
            'imported_mutation_batches': imported_mutation_count,
            'imported_training_batches': imported_training_count,
            'total_submissions_after': len(self.data['submissions']),
            'stats_recalculated': True,
            'message': f'导入完成，已根据 {len(self.data["submissions"])} 条提交记录重新计算统计数据'
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
    data = request.get_json(silent=True) or request.form or {}
    user_input = str(data.get('captcha', '')).strip()
    
    session_id = session.get('session_id')
    if not session_id:
        return jsonify({'success': False, 'error_code': 'session_expired',
                        'message': '会话已过期，请刷新页面', 'show_correction': False}), 400
    
    correct_text = store.get_session_captcha(session_id)
    if not correct_text:
        return jsonify({'success': False, 'error_code': 'captcha_expired',
                        'message': '验证码已过期或已使用，请刷新', 'show_correction': False}), 400
    
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
    data = request.get_json(silent=True) or request.form or {}
    original_text = str(data.get('original_text', '')).strip()
    correct_text = str(data.get('correct_text', '')).strip()
    
    if not original_text or not correct_text:
        return jsonify({'success': False, 'message': '请提供完整信息'}), 400
    
    if not is_valid_captcha_text(original_text) or not is_valid_captcha_text(correct_text):
        return jsonify({'success': False, 'message': '验证码格式无效，仅支持3-8位字母和数字'}), 400
    
    if original_text.upper() == correct_text.upper():
        return jsonify({'success': False, 'message': '纠错内容与原始内容相同，无需提交'}), 400
    
    ip = request.remote_addr
    record = store.add_correction(original_text, correct_text, ip)
    
    if not record:
        return jsonify({'success': False, 'message': '提交失败或该纠错已存在'}), 400
    
    return jsonify({
        'success': True,
        'message': '纠错已提交，感谢您的反馈！',
        'record': record,
        'status': record.get('status', 'trusted')
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


@app.route('/quality')
def quality_page():
    return render_template('quality.html')


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


@app.route('/api/quality/overview')
def api_quality_overview():
    overview = store.get_data_quality_overview()
    summary = store.get_summary()
    return jsonify({
        'success': True,
        'overview': overview,
        'total_tracking': len(overview),
        'summary': summary
    })


@app.route('/api/submissions/filter', methods=['GET', 'POST'])
def api_filter_submissions():
    data = request.get_json(silent=True) or request.args or {}
    result_filter = data.get('result_filter', 'all')
    text_filter = str(data.get('text_filter', '')).strip()
    date_from = str(data.get('date_from', '')).strip()
    date_to = str(data.get('date_to', '')).strip()
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
    data = request.get_json(silent=True) or request.form or {}
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
    data = request.get_json(silent=True) or request.form or {}
    user_input = str(data.get('captcha', '')).strip()
    
    correct_text = store.get_session_captcha(session_id)
    if not correct_text:
        return jsonify({'success': False, 'error_code': 'captcha_expired',
                        'message': '验证码已过期或不存在', 'show_correction': False}), 404
    
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


@app.route('/api/corrections', methods=['GET'])
def api_corrections():
    status_filter = request.args.get('status', 'all')
    corrections = store.get_corrections(status_filter)
    return jsonify({
        'success': True,
        'corrections': corrections,
        'corpus_trusted': store.get_correction_texts(trusted_only=True),
        'corpus_all': store.get_correction_texts(trusted_only=False),
        'count': len(corrections)
    })


@app.route('/api/corrections/<correction_id>', methods=['DELETE'])
def api_delete_correction(correction_id):
    result = store.delete_correction(correction_id)
    if result:
        return jsonify({'success': True, 'message': '已删除该纠错记录'})
    return jsonify({'success': False, 'message': '未找到该记录'}), 404


@app.route('/api/corrections/<correction_id>/status', methods=['PUT', 'POST'])
def api_update_correction_status(correction_id):
    data = request.get_json(silent=True) or request.form or {}
    status = data.get('status', 'trusted')
    if status not in ['trusted', 'suspect', 'discarded']:
        return jsonify({'success': False, 'message': '无效状态'}), 400
    result = store.update_correction_status(correction_id, status)
    if result:
        return jsonify({'success': True, 'message': f'状态已更新为: {status}'})
    return jsonify({'success': False, 'message': '未找到该记录'}), 404


@app.route('/api/generate_from_corrections', methods=['POST'])
def generate_from_corrections():
    data = request.get_json(silent=True) or request.form or {}
    count = int(data.get('count', 5))
    count = min(max(count, 1), 20)
    source = data.get('source', 'trusted_only')
    trusted_only = source != 'all'
    
    corpus = store.get_correction_texts(trusted_only=trusted_only)
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
        'corpus_size': len(corpus),
        'source': source
    })


@app.route('/api/mutation_batches', methods=['GET'])
def api_get_mutation_batches():
    batches = store.get_mutation_batches()
    return jsonify({
        'success': True,
        'batches': batches,
        'count': len(batches)
    })


@app.route('/api/mutation_batches', methods=['POST'])
def api_save_mutation_batch():
    data = request.get_json(silent=True) or request.form or {}
    name = str(data.get('name', '')).strip()
    samples = data.get('samples', [])
    source = data.get('source', 'trusted_only')
    corpus_size = int(data.get('corpus_size', 0))
    
    if not isinstance(samples, list) or len(samples) == 0:
        return jsonify({'success': False, 'message': '无效的样本数据'}), 400
    
    batch = store.add_mutation_batch(name, samples, corpus_size, source)
    return jsonify({
        'success': True,
        'message': '批次已保存',
        'batch': batch
    })


@app.route('/api/mutation_batches/<batch_id>', methods=['DELETE'])
def api_delete_mutation_batch(batch_id):
    result = store.delete_mutation_batch(batch_id)
    if result:
        return jsonify({'success': True, 'message': '批次已删除'})
    return jsonify({'success': False, 'message': '未找到该批次'}), 404


@app.route('/api/generate_correction_preview', methods=['POST'])
def generate_correction_preview():
    data = request.get_json(silent=True) or request.form or {}
    original_text = str(data.get('original_text', '')).strip()
    correct_text = str(data.get('correct_text', '')).strip()
    
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
    import_obj = None
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
    data = request.get_json(silent=True) or request.form or {}
    captcha_text = str(data.get('captcha_text', '')).strip()
    label = str(data.get('label', '')).strip()
    source = str(data.get('source', 'manual')).strip()
    
    record = store.add_annotation(captcha_text, label, source)
    if not record:
        return jsonify({'success': False, 'message': '验证码格式无效'}), 400
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


@app.route('/api/training/batches', methods=['GET'])
def api_get_training_batches():
    limit = int(request.args.get('limit', 20))
    batches = store.get_training_batches(limit)
    return jsonify({
        'success': True,
        'batches': batches,
        'count': len(batches)
    })


@app.route('/api/training/batches', methods=['POST'])
def api_save_training_batch():
    data = request.get_json(silent=True) or request.form or {}
    samples = data.get('samples', [])
    annotations = data.get('annotations', [])
    difficulty = data.get('difficulty', 'auto')
    
    if not isinstance(annotations, list) or len(annotations) == 0:
        return jsonify({'success': False, 'message': '无效的标注数据'}), 400
    
    batch = store.add_training_batch(samples, annotations, difficulty)
    return jsonify({
        'success': True,
        'message': '批次报告已生成',
        'batch': batch
    })


@app.route('/api/training/suggestion')
def api_training_suggestion():
    summary = store.get_summary()
    trend = store.get_accuracy_trend(8)
    training_batches = store.get_training_batches(5)
    
    accuracy = summary.get('accuracy', 0)
    total = summary.get('total_submissions', 0)
    
    suggestion = {
        'recommended_difficulty': 'normal',
        'reason': '',
        'accuracy': accuracy,
        'total_submissions': total,
        'trend': trend,
        'recent_batches': training_batches,
        'next_steps': []
    }
    
    if total < 20:
        suggestion['reason'] = '样本量不足，建议先积累更多标注数据'
        suggestion['recommended_difficulty'] = 'normal'
        suggestion['next_steps'] = [
            '继续在普通模式下收集基础样本',
            '建议至少收集50条记录再调整难度',
            '可在训练模拟区批量标注以快速积累数据'
        ]
    elif accuracy >= 80:
        suggestion['reason'] = '当前识别准确率较高，建议提升难度'
        suggestion['recommended_difficulty'] = 'hard'
        suggestion['next_steps'] = [
            '切换到困难模式获取更有挑战性的样本',
            '使用可信纠错数据生成变异样本进行训练',
            '继续关注训练批次报告中的易错字符'
        ]
    elif accuracy <= 40:
        suggestion['reason'] = '当前识别准确率较低，建议降低难度或增加训练'
        suggestion['recommended_difficulty'] = 'normal'
        suggestion['next_steps'] = [
            '在普通模式下多练习熟悉验证码特征',
            '检查样本库中可疑和已废弃的纠错项',
            '查看数据质量看板，找出高频出错的验证码',
            '在训练模拟区进行批量标注巩固'
        ]
    else:
        suggestion['reason'] = '当前识别准确率中等，可以根据需要调整难度'
        suggestion['recommended_difficulty'] = random.choice(['normal', 'hard'])
        suggestion['next_steps'] = [
            '保持当前难度继续练习',
            '可尝试挑战困难模式',
            '定期查看批次报告跟踪进步',
            '关注易错字符进行针对性训练'
        ]
    
    return jsonify({
        'success': True,
        'suggestion': suggestion
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
