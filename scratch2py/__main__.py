import sys
import json
import io
import importlib
import queue
import math

from zipfile import ZipFile
from pprint import pprint
from queue import Queue
from threading import get_ident
from collections import namedtuple

import cairosvg
import pygame

from . import sb
from .vm import Parser
from .vm import VM

SCREEN_WIDTH = 480
SCREEN_HEIGHT = 360

BB = namedtuple("BB", "x, y, w, h")


def scratch_to_pygame_coord(x, y):
    return (x + SCREEN_WIDTH // 2, - y + SCREEN_HEIGHT // 2)


def pygame_to_scratch_coord(x, y):
    return (x - SCREEN_WIDTH // 2, - y + SCREEN_HEIGHT // 2)


class DummySound:
    def __init__(self, env, sound_info):
        self.name = sound_info["name"]

    def play(self):
        pass


class Sound:
    def __init__(self, env, sound_info):
        si = sound_info
        self.name = si["name"]

        fmt = si["dataFormat"]
        if fmt != "wav":
            raise ValueError("Unsupported sound dataFormat {}".format(fmt))

        snd_file = env.open_file(si["md5ext"])
        # print(si["md5ext"], type(snd_file))
        
        try:
            self._snd = pygame.mixer.Sound(snd_file.read())
        except pygame.error as exc:
            raise ValueError("Error reading sound file {}: {}".format(si["md5ext"], exc))

    def play(self):
        self._snd.play()


class Costume:
    def __init__(self, env, costume_info):
        ci = costume_info
        self.name = ci["name"]
        self._rot_cx = ci["rotationCenterX"]
        self._rot_cy = ci["rotationCenterY"]
        self._bmp_res = ci.get("bitmapResolution", 1)
        # print("BMP Resolution", self._bmp_res)
        fmt = ci["dataFormat"]
        img_file = env.open_file(ci["md5ext"])

        if fmt == "png":
            self._img = self._load_png(img_file)
        elif fmt == "svg":
            self._img = self._load_svg(img_file)
        elif fmt == "jpg":
            self._img = self._load_jpg(img_file)
        else:
            raise ValueError("Unsupported dataFormat {}".format(fmt))

        self._cached = {}

    def _load_png(self, fobj):
        png = fobj.read()
        return pygame.image.load(io.BytesIO(png), "xyz.png")

    def _load_jpg(self, fobj):
        jpg = fobj.read()
        return pygame.image.load(io.BytesIO(jpg), "xyz.jpg")

    def _load_svg(self, fobj):
        png = cairosvg.svg2png(file_obj=fobj)
        return self._load_png(io.BytesIO(png))

    def _scale_rotate(self, size, direction):
        cached = self._cached.get((size, direction), None)
        if cached is not None:
            return cached
                    
        scaled = pygame.transform.scale(self._img,
                                        (int(self._img.get_width() * size // 100 // self._bmp_res),
                                         int(self._img.get_height() * size // 100 // self._bmp_res)))
        rotated = pygame.transform.rotate(scaled, 90 - direction)
        self._cached[(size, direction)] = rotated

        return rotated

    def touches(self, x, y, size, direction, pos_x, pos_y):
        rotated = self._scale_rotate(size, direction)

        sprite_x, sprite_y = scratch_to_pygame_coord(x, y)
        pos_x, pos_y = scratch_to_pygame_coord(pos_x, pos_y)

        pos_x += rotated.get_width() // 2
        pos_y += rotated.get_height() // 2

        pos_x -= sprite_x
        pos_y -= sprite_y

        if pos_x < 0 or pos_y < 0:
            return False

        if pos_x > rotated.get_width() or pos_y > rotated.get_height():
            return False

        r, g, b, a = rotated.get_at((pos_x, pos_y))
        if a == 0:
            return False

        return True

    def draw(self, x, y, size, direction, screen):
        rotated = self._scale_rotate(size, direction)
        x, y = scratch_to_pygame_coord(x - self._rot_cx / self._bmp_res,
                                       y + self._rot_cy / self._bmp_res)
        screen.blit(rotated, (x, y))

    def get_bb(self, x, y, size, direction):
        cached = self._cached.get((size, direction), None)
        if cached == None:
            return BB(0, 0, 0, 0)  # FIXME?
        else:
            x, y = scratch_to_pygame_coord(x - self._rot_cx / self._bmp_res,
                                           y + self._rot_cy / self._bmp_res)
            return BB(x, y, cached.get_width(), cached.get_height())


class Target:
    def __init__(self, info, gvars):
        self._blocks = info["blocks"]
        self._parser = Parser(info, gvars)
        self._gvars = gvars

    def _load_sounds(self, env, si):
        sound_map = {}
        for sound in si["sounds"]:
            try:
                sound = Sound(env, sound)
            except ValueError as exc:
                print("Warning: {}".format(exc))
                sound = DummySound(env, sound)
            sound_map[sound.name] = sound

        return sound_map

    def _load_costumes(self, env, si):
        costumes = []
        for costume in si["costumes"]:
            costume = Costume(env, costume)
            costumes.append(costume)
        return costumes

    def next_costume(self):
        self._curr_costume += 1
        self._curr_costume %= len(self._costumes)

    def draw(self, screen):
        if self._visible:
            # print("Drawing ...", self.name, self.x, self.y)
            self._costumes[self._curr_costume].draw(self.x, self.y,
                                                    self._size,
                                                    self._direction,
                                                    screen)

    def _get_costume_by_name(self, name):
        for i, costume in enumerate(self._costumes):
            if costume.name == name:
                return i

        raise ValueError("Invalid costume {}".format(name))

    def switch_costume(self, name):
        self._curr_costume = self._get_costume_by_name(name)

    def get_hat_actions(self):
        hat_actions = []

        for script, hat in self._parser.get_hats():
            action = VM(self, self._gvars).get_runner(script)
            hat_actions.append((hat, action))

        return hat_actions

    def get_variables(self):
        return self._parser.get_variable_map()


class Stage(Target):
    def __init__(self, env, stage_info):
        Target.__init__(self, stage_info, {})
        
        si = stage_info
        self._env = env
        self.x = 0
        self.y = 0
        self._size = 100
        self._direction = 90
        self._visible = True
        self._curr_costume = si["currentCostume"]
        self._costumes = self._load_costumes(env, si)
        self.name = si["name"]
        self._blocks = si["blocks"]


class Sprite(Target):
    def __init__(self, env, sprite_info, stage):
        Target.__init__(self, sprite_info, stage.get_variables())
        
        si = sprite_info
        self._env = env
        self.x = int(si["x"])
        self.y = int(si["y"])
        self._size = si["size"]
        self._visible = si["visible"]
        self._direction = si["direction"]
        self._curr_costume = si["currentCostume"]
        self.order = si["layerOrder"]
        self._costumes = self._load_costumes(env, si)
        self._sounds = self._load_sounds(env, si)
        self._blocks = si["blocks"]
        self.name = si["name"]

    def go_to_xy(self, x, y):
        self.x = x
        self.y = y

    def change_x_by(self, n):
        self.x += n

    def set_x_to(self, x):
        self.x = x

    def change_y_by(self, n):
        self.y += n

    def set_y_to(self, y):
        self.y = y

    def set_size_to(self, size):
        self._size = size

    def point_in_direction(self, direction):
        self._direction = direction

    def turn_anti_clockwise(self, degrees):
        self._direction -= degrees

    def turn_clockwise(self, degrees):
        self._direction += degrees

    def touches(self, x, y):
        return self._costumes[self._curr_costume].touches(self.x, self.y,
                                                          self._size,
                                                          self._direction,
                                                          x, y)

    def start_sound(self, name):
        self._sounds[name].play()

    def stop_all_sounds(self):
        pygame.mixer.stop()

    def say(self, msg):
        print(msg)

    def dump_blocks(self):
        vm = VM(self, self._blocks)
        for bid, _ in vm.get_hats():
            vm.dump(bid)

    def _bb_collision(self, bb1, bb2):
        return not ((bb1.x > bb2.x + bb2.w - 1) or # is b1 on the right side of b2?
                    (bb1.y > bb2.y + bb2.h - 1) or # is b1 under b2?
                    (bb2.x > bb1.x + bb1.w - 1) or # is b2 on the right side of b1?
                    (bb2.y > bb1.y + bb1.h - 1))   # is b2 under b1?

    def touching(self, name):
        sprite = self._env.get_sprite_by_name(name)
        bb1 = self.get_bb()
        bb2 = sprite.get_bb()
        return self._bb_collision(bb1, bb2)
        
    def get_bb(self):
        return self._costumes[self._curr_costume].get_bb(self.x, self.y,
                                                         self._size,
                                                         self._direction)

    def move(self, steps):
        theta = math.radians(90 - self._direction)
        self.x += steps * math.cos(theta)
        self.y += steps * math.sin(theta)

    def if_on_edge_bounce(self):
        # FIXME: WIP
        maxx, miny = pygame_to_scratch_coord(SCREEN_WIDTH, SCREEN_HEIGHT)
        minx, maxy = pygame_to_scratch_coord(0, 0)
        
        if (self.x > maxx or self.x < minx or self.y > maxy or self.y < miny):
            self._direction = -self._direction

class ScratchEnv:
    def __init__(self, proj_filename, package_name):
        self._zip_file = ZipFile(proj_filename)
        self._proj = self._load_project()
        self._package_name = package_name
        if package_name is None:
            self._package = None
        else:
            self._package = importlib.import_module(package_name)
        self._stage = self._load_stage()
        self._sprites = self._load_sprites()

    def open_file(self, filename):
        return self._zip_file.open(filename, "r")
        
    def _load_project(self):
        proj_file = self._zip_file.open("project.json", "r")
        proj_json = proj_file.read().decode("utf-8")
        return json.loads(proj_json)

    def _load_stage(self):
        stage = None
        for target in self._proj["targets"]:
            if target["isStage"]:
                stage = Stage(self, target)

        return stage

    def _load_sprites(self):
        sprites = {}
        stage = None
        for target in self._proj["targets"]:
            if not target["isStage"]:
                name = target["name"]
                if self._package_name is not None:
                    try:
                        importlib.import_module(self._package_name + "." + name)
                    except ImportError:
                        pass
                sprite = Sprite(self, target, self._stage)
                sb.register_scratch_tasks(sprite)
                sprites[name] = sprite

        return sprites

    def draw(self, screen):
        self._stage.draw(screen)
        sprites = self._sprites.values()
        for sprite in sorted(sprites, key=lambda s: s.order):
            sprite.draw(screen)

    def get_sprite_by_name(self, name):
        return self._sprites[name]

    def _broadcast(self, message):
        hat = sb.HatReceived(message)
        return sb.activate_hats(hat, None, self)

    def broadcast(self, message):
        self._broadcast(message)

    def broadcast_and_wait(self, message):
        activated = self._broadcast(message)

        # Wait for all activated threads to complete
        for thread in activated:
            thread.join()

    def dump_blocks(self):
        for sprite in self._sprites:
            print("\n\n<<{}>>\n\n".format(sprite))
            self._sprites[sprite].dump_blocks()

    def run(self):
        pygame.key.set_repeat(10)

        clock = pygame.time.Clock()
        screen = pygame.display.set_mode((480, 360))

        flag_clicked = sb.HatFlagClicked()
        sb.activate_hats(flag_clicked, None, self)

        while True:
            screen.fill((0xFF, 0xFF, 0xFF))
            self.draw(screen)
            pygame.display.flip()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    sys.exit(0)
                elif event.type == pygame.KEYDOWN:
                    try:
                        key_pressed = sb.HatKeyPressed.from_code(event.key)
                        sb.activate_hats(key_pressed, None, self)
                    except ValueError:
                        pass
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    x, y = pygame.mouse.get_pos()
                    x, y = pygame_to_scratch_coord(x, y)
                    sprite_clicked = sb.HatSpriteClicked()
                    sb.activate_hats(sprite_clicked, (x, y), self)

            clock.tick(40)


def main():
    if len(sys.argv) not in [3, 4]:
        print("scratch2py <cmd> <scratch-project> [<code-package>]")
        exit(1)

    pygame.init()
        
    cmd = sys.argv[1]
    sb3_filename = sys.argv[2]
    py_package = None
    if len(sys.argv) == 4:
        py_package = sys.argv[3]
        
    env = ScratchEnv(sb3_filename, py_package)

    if cmd == "run":
        env.run()
    elif cmd == "dump-blocks":
        env.dump_blocks()


main()

