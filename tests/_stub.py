"""Minimal `genlayer` SDK stub so the contract module imports under plain CPython.

The contract only runs inside GenVM. Everything in Precedence that decides
anything is a module level pure function, so a stub is enough to reach all of
it: the normaliser, the similarity sweep, the prompt discipline, the
agreement rule, and the judgement itself.

Nothing here simulates consensus. `run_nondet_unsafe` just runs the leader, so
these tests never assert anything about validator behaviour. What they assert
is the shape of what a validator would compare.
"""
import sys
import types


def install() -> None:
    if "genlayer" in sys.modules:
        return

    class UserError(Exception):
        def __init__(self, message: str = ""):
            super().__init__(message)
            self.message = message

    class Return:
        def __init__(self, calldata):
            self.calldata = calldata

    def identity(fn):
        return fn

    write = identity
    write.payable = identity

    vm = types.SimpleNamespace(
        UserError=UserError,
        Return=Return,
        Result=object,
        run_nondet_unsafe=lambda leader, validator: leader(),
    )
    nondet = types.SimpleNamespace(
        exec_prompt=lambda *a, **k: "",
        web=types.SimpleNamespace(
            render=lambda *a, **k: "",
            get=lambda *a, **k: types.SimpleNamespace(body=b"", status_code=200),
            request=lambda *a, **k: types.SimpleNamespace(body=b"", status_code=200),
        ),
    )
    storage = types.SimpleNamespace(
        copy_to_memory=lambda x: x,
        inmem_allocate=lambda t, *a, **k: list(a[0]) if a else [],
    )

    # The EVM interface decorator is only used to name a bare recipient for a
    # value transfer, so the stub keeps the class and gives it a transfer that
    # records rather than sends.
    def contract_interface(cls):
        class _Bound:
            sent = []

            def __init__(self, address):
                self.address = address

            def emit_transfer(self, value=0, **kwargs):
                _Bound.sent.append((self.address, value))

            def emit(self, *a, **k):
                return self

        _Bound.__name__ = cls.__name__
        return _Bound

    gl = types.SimpleNamespace(
        Contract=object,
        vm=vm,
        nondet=nondet,
        storage=storage,
        evm=types.SimpleNamespace(contract_interface=contract_interface),
        public=types.SimpleNamespace(view=identity, write=write),
        message=types.SimpleNamespace(
            sender_address="0x" + "11" * 20,
            value=0,
        ),
        message_raw={"datetime": "2026-09-07T00:00:00+00:00"},
    )

    class _Generic:
        def __class_getitem__(cls, item):
            return dict

    mod = types.ModuleType("genlayer")
    mod.gl = gl
    mod.allow_storage = identity
    mod.Address = str
    for _name in ("u8", "u16", "u32", "u64", "u128", "u256",
                  "i8", "i16", "i32", "i64", "i128", "i256"):
        setattr(mod, _name, int)
    mod.DynArray = _Generic
    mod.TreeMap = _Generic
    mod.__all__ = ["gl", "allow_storage", "Address", "DynArray", "TreeMap",
                   "u8", "u16", "u32", "u64", "u128", "u256",
                   "i8", "i16", "i32", "i64", "i128", "i256"]
    sys.modules["genlayer"] = mod
