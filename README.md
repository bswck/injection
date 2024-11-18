# injection

## How does that work?
_injection_ makes it possible to hook into variable name lookup via inserting a special key into scope dictionaries.

### Example
```py
from functools import partial
from random import randint

from injection import inject

roll: int
inject("roll", into=locals(), factory=partial(randint, 1, 6))

print(roll, type(roll) is int)  # 6 True
print(roll, type(roll) is int)  # 4 True
print(roll, type(roll) is int)  # 3 True

# you never know what the value of roll will be!
```

It could be used for various purposes, for instance as a robust replacement for Flask's [local proxies](https://flask.palletsprojects.com/en/stable/reqcontext/#notes-on-proxies) or to implement pure-Python PEP 690
that would import things on first reference.

# Legal Info
© Copyright by Bartosz Sławecki ([@bswck](https://github.com/bswck)).
<br />This software is licensed under the terms of [MIT License](https://github.com/bswck/injection/blob/HEAD/LICENSE).
