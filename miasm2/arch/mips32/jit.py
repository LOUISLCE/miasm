import logging

from miasm2.jitter.jitload import jitter
from miasm2.core import asmblock
from miasm2.core.utils import pck32, upck32
from miasm2.arch.mips32.sem import ir_mips32l, ir_mips32b
from miasm2.jitter.codegen import CGen
from miasm2.ir.ir import AssignBlock, IRBlock
import miasm2.expression.expression as m2_expr

log = logging.getLogger('jit_mips32')
hnd = logging.StreamHandler()
hnd.setFormatter(logging.Formatter("[%(levelname)s]: %(message)s"))
log.addHandler(hnd)
log.setLevel(logging.CRITICAL)


class mipsCGen(CGen):
    CODE_INIT = CGen.CODE_INIT + r"""
    unsigned int branch_dst_pc;
    unsigned int branch_dst_irdst;
    unsigned int branch_dst_set=0;
    """

    CODE_RETURN_NO_EXCEPTION = r"""
    %s:
    if (branch_dst_set) {
        %s = %s;
        BlockDst->address = %s;
    } else {
        BlockDst->address = %s;
    }
    return JIT_RET_NO_EXCEPTION;
    """

    def __init__(self, ir_arch):
        super(mipsCGen, self).__init__(ir_arch)
        self.delay_slot_dst = m2_expr.ExprId("branch_dst_irdst", 32)
        self.delay_slot_set = m2_expr.ExprId("branch_dst_set", 32)

    def block2assignblks(self, block):
        irblocks_list = super(mipsCGen, self).block2assignblks(block)
        for irblocks in irblocks_list:
            for blk_idx, irblock in enumerate(irblocks):
                has_breakflow = any(assignblock.instr.breakflow() for assignblock in irblock)
                if not has_breakflow:
                    continue

                irs = []
                for assignblock in irblock:
                    if self.ir_arch.pc not in assignblock:
                        irs.append(AssignBlock(assignments, assignblock.instr))
                        continue
                    assignments = dict(assignblock)
                    # Add internal branch destination
                    assignments[self.delay_slot_dst] = assignblock[
                        self.ir_arch.pc]
                    assignments[self.delay_slot_set] = m2_expr.ExprInt(1, 32)
                    # Replace IRDst with next instruction
                    assignments[self.ir_arch.IRDst] = m2_expr.ExprId(
                        self.ir_arch.get_next_instr(assignblock.instr), 32)
                    irs.append(AssignBlock(assignments, assignblock.instr))
                irblocks[blk_idx] = IRBlock(irblock.label, irs)

        return irblocks_list

    def gen_finalize(self, block):
        """
        Generate the C code for the final block instruction
        """

        lbl = self.get_block_post_label(block)
        out = (self.CODE_RETURN_NO_EXCEPTION % (self.label_to_jitlabel(lbl),
                                                self.C_PC,
                                                m2_expr.ExprId('branch_dst_irdst', 32),
                                                m2_expr.ExprId('branch_dst_irdst', 32),
                                                self.id_to_c(m2_expr.ExprInt(lbl.offset, 32)))
              ).split('\n')
        return out


class jitter_mips32l(jitter):

    C_Gen = mipsCGen

    def __init__(self, *args, **kwargs):
        sp = asmblock.AsmSymbolPool()
        jitter.__init__(self, ir_mips32l(sp), *args, **kwargs)
        self.vm.set_little_endian()

    def push_uint32_t(self, value):
        self.cpu.SP -= 4
        self.vm.set_mem(self.cpu.SP, pck32(value))

    def pop_uint32_t(self):
        value = upck32(self.vm.get_mem(self.cpu.SP, 4))
        self.cpu.SP += 4
        return value

    def get_stack_arg(self, index):
        return upck32(self.vm.get_mem(self.cpu.SP + 4 * index, 4))

    def init_run(self, *args, **kwargs):
        jitter.init_run(self, *args, **kwargs)
        self.cpu.PC = self.pc


class jitter_mips32b(jitter_mips32l):

    def __init__(self, *args, **kwargs):
        sp = asmblock.AsmSymbolPool()
        jitter.__init__(self, ir_mips32b(sp), *args, **kwargs)
        self.vm.set_big_endian()
