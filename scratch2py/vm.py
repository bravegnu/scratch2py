import time
import keyword
import random

from . import sb

class IEval:
    def eval(self, vm):
        raise NotImplementedError("eval")


class Color(IEval):
    def __init__(self, string):
        string = string[1:]
        self.red = int(string[1:3], 16)
        self.green = int(string[3:5], 16)
        self.blue = int(string[5:6], 16)

    def eval(self, vm):
        return self


class Variable(IEval):
    def __init__(self, name, value):
        self._name = name
        self._value = value

    def set_value(self, value):
        self._value = value

    def get_value(self):
        return self._value

    def eval(self, vm):
        return self._value


class Literal(IEval):
    def __init__(self, const):
        self._const = const

    def eval(self, vm):
        return self._const


class Block:
    def __init__(self, block, parser):
        self._opcode = block["opcode"]
        self._kwargs = {}
        
        for inp, arg in block["fields"].items():
            self._kwargs[inp.lower()] = arg[0]

        for inp, arg in block["inputs"].items():
            self._kwargs[inp.lower()] = self._parse_arg(arg[1], parser)

    def _parse_arg(self, arg, parser):
        if isinstance(arg, str):
            return Script(arg, parser)
        else:
            return self._parse_val(arg, parser)

    def _parse_val(self, arg, parser):
        if arg is None:
            return arg
        elif arg[0] in [4, 5]:
            return Literal(float(arg[1]))
        elif arg[0] in [6, 7, 8]:
            return Literal(int(arg[1]))
        elif arg[0] in [9]:
            return Color(arg[1])
        elif arg[0] in [10]:
            return Literal(arg[1])
        elif arg[0] in [11, 13]:
            return Literal(arg[1])
        elif arg[0] in [12]:
            return parser.get_variable(arg[1])
        else:
            raise ValueError("unknown data type {}".format(arg[0]))
            
    def execute(self, vm):
        if self._opcode.startswith("event_"):
            return
        
        method = getattr(vm, "op_" + self._opcode)
        for kw in keyword.kwlist:
            if kw in self._kwargs:
                val = self._kwargs[kw]
                self._kwargs[kw + "_"] = val
                self._kwargs.pop(kw)
                
        return method(**self._kwargs)

    def __str__(self):
        return "Block({})".format(self._opcode)


class Script(IEval):
    def __init__(self, entry, parser):
        bid = entry
        self._seq = []

        while bid is not None:
            block = parser.blocks[bid]
            b = Block(block, parser)
            self._seq.append(b)
            bid = block["next"]

    def eval(self, vm):
        retval = None
        for block in self._seq:
            retval = block.execute(vm)
            import time
            time.sleep(0.001)
        return retval

    def __repr__(self):
        return "\n".join(str(block) for block in self._seq)


class Parser:
    def __init__(self, sprite_info, gvars):
        self._sinfo = sprite_info
        self._gvars = gvars
        self._lvars = {}
        self._hats = []

        self.blocks = self._sinfo["blocks"]

        self._parse_blocks()
        self._parse_variables()

    def _parse_variables(self):
        for vid, vinfo in self._sinfo["variables"].items():
            name = vinfo[0]
            value = vinfo[1]
            self._lvars[name] = Variable(name, value)

    def _parse_blocks(self):
        self._hats = []
        for bid, block in self.blocks.items():
            if isinstance(block, dict) and block["topLevel"]:
                if block["opcode"].startswith("event_"):
                    script = Script(bid, self)
                    hat = None
                     
                    if block["opcode"] == "event_whenflagclicked":
                        hat = sb.HatFlagClicked()

                    elif block["opcode"] == "event_whenkeypressed":
                        key = block["fields"]["KEY_OPTION"][0]
                        hat = sb.HatKeyPressed.from_name(key)

                    if hat is not None:
                        self._hats.append((script, hat))

    def get_hats(self):
        return self._hats

    def get_variable_map(self):
        return self._lvars

    def get_variable(self, var):
        try:
            return self._lvars[var]
        except KeyError:
            try:
                return self._gvars[var]
            except KeyError:
                raise ValueError("Invalid variable name {}".format(var))


class VM:
    def __init__(self, target, gvars):
        self._target = target
        self._gvars = gvars
        self._lvars = target.get_variables()

    def op_unsupported(self, **kwargs):
        print(kwargs)

    def __getattr__(self, attr):
        if attr.startswith("op_"):
            print("Warning: Unsupported op {}".format(attr))
            return self.op_unsupported
        raise AttributeError(attr)

    def op_control_stop(self, stop_option):
        # FIXME: Stop all threads?
        exit(0)

    def op_control_wait(self, duration):
        time.sleep(self._eval(duration))

    def op_control_forever(self, substack):
        while True:
            self._eval(substack)

    def op_control_repeat(self, times, substack):
        for i in range(self._eval(times)):
            self._eval(substack)

    def op_control_if(self, condition, substack):
        if self._eval(condition):
            self._eval(substack)

    def op_control_wait_until(self, condition):
        while not self._eval(condition):
            pass

    def op_looks_say(self, message):
        return self._target.say(self._eval(message))

    def op_looks_nextcostume(self):
        return self._target.next_costume()

    def op_motion_yposition(self):
        return self._target.y

    def op_motion_xposition(self):
        return self._target.x

    def op_motion_movesteps(self, steps):
        return self._target.move(self._eval(steps))

    def op_motion_ifonedgebounce(self):
        return self._target.if_on_edge_bounce()

    def op_sensing_touchingobjectmenu(self, touchingobjectmenu):
        return touchingobjectmenu

    def op_sensing_touchingobject(self, touchingobjectmenu):
        sprite = self._eval(touchingobjectmenu)
        return self._target.touching(sprite)

    def _compare(self, operand1, operand2):
        op1 = self._eval(operand1)
        op2 = self._eval(operand2)

        try:
            num1 = float(op1)
            num2 = float(op2)

            return num1 - num2
        except ValueError:
            str1 = op1
            str2 = op2

            str1 = str1.lower()
            str2 = str2.lower()

            if str1 < str2:
                return -1
            elif str1 > str2:
                return 1
            else:
                return 0

    def op_operator_gt(self, operand1, operand2):
        return self._compare(operand1, operand2) > 0

    def op_operator_lt(self, operand1, operand2):
        return self._compare(operand1, operand2) < 0

    def op_operator_equals(self, operand1, operand2):
        return self._compare(operand1, operand2) == 0

    def op_operator_and(self, operand1, operand2):
        return self._eval(operand1) and self._eval(operand2)

    def op_operator_or(self, operand1, operand2):
        return self._eval(operand1) or self._eval(operand2)

    def op_operator_not(self, operand):
        return not self._eval(operand)

    def op_operator_random(self, from_, to):
        low = self._eval(from_)
        high = self._eval(to) 
        rnd = (random.random() * (high - low)) + low
        
        if isinstance(low, int) and isinstance(high, int):
            return int(rnd)
        else:
            return rnd

    def op_operator_join(self, string1, string2):
        return self._eval(string1) + self._eval(string2)

    def op_operator_letter_of(self, letter, string):
        letter = self._eval(letter)
        string = self._eval(string)
        return string[letter]

    def op_operator_length(self, string):
        return len(self._eval(string))

    def op_operator_contains(self, string1, string2):
        return self._eval(string1).lower() in self._eval(string2).lower()

    def op_operator_round(self, num):
        return math.round(self._eval(num))

    def op_operator_mod(self, num1, num2):
        return self._eval(num1) % self._eval(num2)

    def op_operator_add(self, num1, num2):
        return float(self._eval(num1)) + float(self._eval(num2))

    def op_operator_subtract(self, num1, num2):
        return float(self._eval(num1)) + float(self._eval(num2))

    def op_operator_multiply(self, num1, num2):
        return float(self._eval(num1)) * float(self._eval(num2))

    def op_operator_divide(self, num1, num2):
        return float(self._eval(num1)) / float(self._eval(num2))

    def op_operator_mathop(self, operator, num):
        mathops = {
            "abs": abs,
            "floor": math.floor,
            "ceiling": math.ceil,
            "sqrt": math.sqrt,
            "sin": math.sin,
            "cos": math.cos,
            "tan": math.tan,
            "asin": math.asin,
            "acos": math.acos,
            "atan": math.atan,
            "ln": math.log,
            "log": math.log10,
            "e ^": lambda x: math.pow(e, x),
            "10 ^": lambda x: math.pow(10, x)
        }
        
        op = mathops[self.eval(operator)]
        return op(self.eval(num))

    def op_motion_changexby(self, dx):
        self._target.x += int(self._eval(dx))

    def op_motion_changeyby(self, dy):
        self._target.y += int(self._eval(dy))

    def op_motion_setx(self, x):
        self._target.x = int(self._eval(x))

    def op_motion_sety(self, y):
        self._target.y = int(self._eval(y))

    def op_motion_pointindirection(self, direction):
        self._target.point_in_direction(self._eval(direction))

    def op_data_setvariableto(self, variable, value):
        self.get_variable(variable).set_value(self._eval(value))

    def _eval(self, arg):
        return arg.eval(self)

    def get_runner(self, script):
        def run(sprite, env):
            self._eval(script)

        return run

    def get_variable(self, var):
        try:
            return self._lvars[var]
        except KeyError:
            try:
                return self._gvars[var]
            except KeyError:
                raise ValueError("Invalid variable name {}".format(var))

