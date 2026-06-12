import random
import string
import io
from PIL import Image, ImageDraw, ImageFont, ImageFilter


class CaptchaGenerator:
    def __init__(self, width=160, height=60, char_count=4, difficulty='normal'):
        self.width = width
        self.height = height
        self.char_count = char_count
        self.difficulty = difficulty
        self.chars = string.ascii_uppercase + string.digits
        self.font_sizes = [36, 40, 44, 48]
        self.colors = [
            (0, 0, 0), (50, 50, 50), (100, 100, 100),
            (150, 0, 0), (0, 100, 0), (0, 0, 150),
            (150, 100, 0), (100, 0, 150), (0, 100, 150)
        ]
        self.mutation_corpus = []

    def set_mutation_corpus(self, corpus):
        self.mutation_corpus = [text.upper() for text in corpus if text]

    def generate_text(self):
        if self.difficulty == 'hard' and self.mutation_corpus and random.random() < 0.5:
            base_text = random.choice(self.mutation_corpus)
            return self._mutate_text(base_text)
        return ''.join(random.choice(self.chars) for _ in range(self.char_count))

    def _mutate_text(self, base_text):
        mutation_type = random.choice(['case', 'char', 'length', 'shuffle', 'none'])
        text = list(base_text)
        
        if mutation_type == 'case' and len(text) >= 1:
            idx = random.randint(0, len(text) - 1)
            if text[idx].isalpha():
                text[idx] = text[idx].lower() if text[idx].isupper() else text[idx].upper()
        
        elif mutation_type == 'char':
            if len(text) >= 1:
                idx = random.randint(0, len(text) - 1)
                text[idx] = random.choice(self.chars)
        
        elif mutation_type == 'length' and len(text) >= 2:
            if random.random() < 0.5 and len(text) > 2:
                del text[random.randint(0, len(text) - 1)]
            else:
                text.insert(random.randint(0, len(text)), random.choice(self.chars))
        
        elif mutation_type == 'shuffle' and len(text) >= 3:
            random.shuffle(text)
        
        result = ''.join(text)
        if len(result) < 3:
            result += ''.join(random.choice(self.chars) for _ in range(3 - len(result)))
        elif len(result) > 6:
            result = result[:6]
        return result.upper()

    def _get_font(self):
        try:
            font_size = random.choice(self.font_sizes)
            return ImageFont.truetype("arial.ttf", font_size)
        except:
            return ImageFont.load_default()

    def _random_color(self, dark=True):
        if dark:
            return (random.randint(0, 120), random.randint(0, 120), random.randint(0, 120))
        return (random.randint(130, 255), random.randint(130, 255), random.randint(130, 255))

    def generate_image(self, text=None):
        if text is None:
            text = self.generate_text()
        
        image = Image.new('RGB', (self.width, self.height), (255, 255, 255))
        draw = ImageDraw.Draw(image)
        font = self._get_font()
        
        self._draw_background_noise(draw)
        self._draw_lines(draw)
        self._draw_text(draw, text, font)
        self._draw_points(draw)
        
        if self.difficulty == 'hard':
            image = image.filter(ImageFilter.GaussianBlur(radius=0.5))
        
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        buffer.seek(0)
        return buffer, text.upper()

    def _draw_background_noise(self, draw):
        noise_level = 30 if self.difficulty == 'hard' else 15
        for _ in range(random.randint(noise_level, noise_level * 2)):
            x1 = random.randint(0, self.width)
            y1 = random.randint(0, self.height)
            x2 = x1 + random.randint(-5, 5)
            y2 = y1 + random.randint(-5, 5)
            draw.line([(x1, y1), (x2, y2)], fill=self._random_color(dark=False), width=1)

    def _draw_lines(self, draw):
        line_count = 4 if self.difficulty == 'hard' else 2
        for _ in range(random.randint(line_count, line_count + 2)):
            x1 = random.randint(0, self.width)
            y1 = random.randint(0, self.height)
            x2 = random.randint(0, self.width)
            y2 = random.randint(0, self.height)
            draw.line([(x1, y1), (x2, y2)], fill=self._random_color(), width=random.randint(1, 2))

    def _draw_text(self, draw, text, font):
        char_width = self.width / len(text)
        for i, char in enumerate(text):
            x = i * char_width + random.randint(5, 15)
            y = random.randint(5, 15)
            
            if self.difficulty == 'hard':
                angle = random.randint(-25, 25)
            else:
                angle = random.randint(-15, 15)
            
            char_image = Image.new('RGBA', (50, 60), (0, 0, 0, 0))
            char_draw = ImageDraw.Draw(char_image)
            char_draw.text((5, 5), char, font=font, fill=self._random_color())
            char_image = char_image.rotate(angle, resample=Image.BICUBIC, expand=True)
            
            image = draw._image
            image.paste(char_image, (int(x), int(y)), char_image)

    def _draw_points(self, draw):
        point_count = 80 if self.difficulty == 'hard' else 40
        for _ in range(random.randint(point_count, point_count * 2)):
            x = random.randint(0, self.width)
            y = random.randint(0, self.height)
            size = random.randint(1, 2)
            draw.ellipse([x, y, x + size, y + size], fill=self._random_color())

    def set_difficulty(self, difficulty):
        self.difficulty = difficulty
