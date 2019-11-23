import string
import time
import threading

from threading import Thread

tasks_by_hat = {}

class HatBase:
    def __eq__(self, other):
        if type(self) != type(other):
            return False

        return True

    def __hash__(self):
        return hash(0)

    def condition(self, data, env, sprite):
        return True


class HatFlagClicked(HatBase):
    pass


class HatKeyPressed(HatBase):
    KEY_NAME_LIST = (["space", "up arrow", "down arrow", "right arrow", "left arrow", "any"] +
                     list(string.ascii_lowercase) + list(string.digits))

    KEY_CODE_LIST = ([0x20, 0x111, 0x112, 0x113, 0x114, 0xFFFF] +
                     list(bytes(string.ascii_lowercase + string.digits, "ascii")))

    def __init__(self, key_index):
        self._key_index = key_index

    @classmethod
    def name_to_index(cls, name):
        return cls.KEY_NAME_LIST.index(name)

    @classmethod
    def code_to_index(cls, code):
        return cls.KEY_CODE_LIST.index(code)

    @classmethod
    def from_name(cls, name):
        return cls(cls.name_to_index(name))

    @classmethod
    def from_code(cls, code):
        return cls(cls.code_to_index(code))

    def __eq__(self, other):
        if type(self) != type(other):
            return False

        if self._key_index == 0xFFFF or other._key_index == 0xFFFF:
            return True
        
        if self._key_index != other._key_index:
            return False

        return True

    def __hash__(self):
        return hash(self._key_index)
        

class HatSpriteClicked(HatBase):
    def condition(self, data, env, sprite):
        return sprite.touches(*data)


class HatString(HatBase):
    def __init__(self, string):
        self._string = string

    def __eq__(self, other):
        if type(self) != type(other):
            return False
        
        if self._string != other._string:
            return False

        return True

    def __hash__(self):
        return hash(self._string)


class HatBackdropSwitches(HatString):
    pass


class HatReceived(HatString):
    pass


class Task:
    def __init__(self, sprite, action):
        self.sprite = sprite
        self.action = action
        self.activated = False
        self.thread = None


def register(hat, sprite, action):
    global tasks_by_hat

    if hat not in tasks_by_hat:
        tasks_by_hat[hat] = []

    tasks_by_hat[hat].append(Task(sprite, action))


def register_scratch_tasks(sprite):
    global tasks_by_hat

    hat_actions = sprite.get_hat_actions()
    for hat, action in hat_actions:
        register(hat, sprite.name, action)


def get_module_name(func):
    return func.__module__.split(".")[-1]


def when_this_sprite_clicked(func):
    hat = HatSpriteClicked()
    register(hat, get_module_name(func), func)


def when_key_pressed(keyname):
    def _when_key_pressed(func):
        hat = HatKeyPressed.from_name(keyname)
        register(hat, get_module_name(func), func)

    return _when_key_pressed


def when_flag_clicked(func):
    hat = HatFlagClicked()
    register(hat, get_module_name(func), func)


def when_backdrop_switches(backdrop_name):
    def _when_backdrop_switches(func):
        hat = HatBackdropSwitches(backdrop_name)
        register(hat, get_module_name(func), func)

    return _when_backdrop_switches


def when_received(message):
    def _when_received(func):
        hat = HatReceived(message)
        register(hat, get_module_name(func), func)

    return _when_received


def activate_hats(hat, data, env):
    activated = []
    tasks = tasks_by_hat[hat] if hat in tasks_by_hat else []

    for t in tasks:
        sprite = env.get_sprite_by_name(t.sprite)
        
        if t.thread and not t.thread.is_alive():
            t.activated = False
            t.thread = None
            
        if not t.activated and hat.condition(data, env, sprite):
            t.thread = Thread(target=t.action, args=(sprite, env))
            t.thread.daemon = True
            t.activated = True
            t.thread.start()
            activated.append(t.thread)

    return activated

        
