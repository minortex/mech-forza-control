"""Shared in-memory EC backends for command-level tests."""

from src.io import EC_OP_READ, EC_OP_UPDATE_BITS


class FakeBackend:
    """Byte-at-a-time backend without native block or transaction support."""

    def __init__(self, initial=None):
        self.values = dict(initial or {})
        self.writes = []
        self.closed = False

    def open(self):
        pass

    def close(self):
        self.closed = True

    def ec_read(self, addr):
        return self.values.get(addr, 0)

    def ec_write(self, addr, value):
        self.writes.append((addr, value))
        self.values[addr] = value


class NativeBatchBackend(FakeBackend):
    """Backend exposing block and atomic vector ioctls like the kernel module."""

    def __init__(self, initial=None):
        super().__init__(initial)
        self.transactions = []
        self.block_reads = []
        self.block_writes = []

    def ec_read_block(self, addr, length):
        self.block_reads.append((addr, length))
        return bytes(self.ec_read(addr + i) for i in range(length))

    def ec_write_block(self, addr, payload):
        payload = bytes(payload)
        self.block_writes.append((addr, payload))
        for offset, value in enumerate(payload):
            self.ec_write(addr + offset, value)

    def ec_transaction(self, operations):
        operations = list(operations)
        self.transactions.append(operations)
        results = []
        for op in operations:
            if op.type == EC_OP_READ:
                result = self.ec_read(op.addr)
            elif op.type == EC_OP_UPDATE_BITS:
                current = self.ec_read(op.addr)
                result = (current & ~op.mask) | (op.value & op.mask)
                self.ec_write(op.addr, result)
            else:
                self.ec_write(op.addr, op.value)
                result = op.value
            results.append(result)
        return results
