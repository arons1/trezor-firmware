if not __debug__:
    from trezor.utils import halt

    halt("debug mode inactive")

if __debug__:
    from trezor import config, loop, utils
    from trezor.log import _log, WARNING
    from trezor.messages import MessageType
    from trezor.wire import register, protobuf_workflow
    from trezor.messages.Success import Success

    import utime

    if False:
        from typing import Any, List, Optional
        from trezor import wire
        from trezor.messages.DebugLinkDecision import DebugLinkDecision
        from trezor.messages.DebugLinkGetState import DebugLinkGetState
        from trezor.messages.DebugLinkState import DebugLinkState

    reset_internal_entropy = None  # type: Optional[bytes]
    reset_current_words = None  # type: Optional[List[str]]
    reset_word_index = None  # type: Optional[int]

    class feedback_signal(loop.signal):
        def reset(self) -> None:
            self.feedback = None
            super().reset()

        def send(self, feedback: loop.signal, value: Any) -> None:
            if self.feedback is not None:
                _log(__name__, WARNING, "overwrote feedback")
                self.feedback.send(False)
            self.feedback = feedback
            super().send(value)

        def _deliver(self) -> None:
            async def notify(feedback):
                feedback.send(True)

            if self.task is not None and self.value is not loop._NO_VALUE:
                now = utime.ticks_us()
                loop.schedule(self.task, self.value, now)
                loop.schedule(notify(self.feedback), None, now + 1)
                self.reset()

        def __iter__(self) -> loop.Task:  # type: ignore
            try:
                return super().__iter__()
            except:  # noqa: E722
                self.feedback.send(False)
                raise

    confirm_signal = feedback_signal()
    swipe_signal = feedback_signal()
    input_signal = feedback_signal()

    async def dispatch_DebugLinkDecision(
        ctx: wire.Context, msg: DebugLinkDecision
    ) -> Optional[Success]:
        from trezor.ui import confirm, swipe

        debug_feedback = loop.signal()

        waiting_signals = [
            s.value is not loop._NO_VALUE
            for s in (confirm_signal, swipe_signal, input_signal)
        ]
        if sum(waiting_signals) > 0:
            _log(
                __name__,
                WARNING,
                "Received new DebugLinkDecision before the previous one was handled.",
            )
            _log(
                __name__,
                WARNING,
                "received: button {}, swipe {}, input {}".format(
                    msg.yes_no, msg.up_down, msg.input
                ),
            )
            _log(
                __name__,
                WARNING,
                "waiting: button {}, swipe {}, input {}".format(waiting_signals),
            )

        if msg.yes_no is not None:
            confirm_signal.send(
                debug_feedback, confirm.CONFIRMED if msg.yes_no else confirm.CANCELLED
            )
        if msg.up_down is not None:
            swipe_signal.send(
                debug_feedback, swipe.SWIPE_DOWN if msg.up_down else swipe.SWIPE_UP
            )
        if msg.input is not None:
            input_signal.send(debug_feedback, msg.input)

        if msg.wait:
            await debug_feedback
            return Success()

        return None

    async def dispatch_DebugLinkGetState(
        ctx: wire.Context, msg: DebugLinkGetState
    ) -> DebugLinkState:
        from trezor.messages.DebugLinkState import DebugLinkState
        from apps.common import storage, mnemonic

        m = DebugLinkState()
        m.mnemonic_secret = mnemonic.get_secret()
        m.mnemonic_type = mnemonic.get_type()
        m.passphrase_protection = storage.device.has_passphrase()
        m.reset_word_pos = reset_word_index
        m.reset_entropy = reset_internal_entropy
        if reset_current_words:
            m.reset_word = " ".join(reset_current_words)
        return m

    def boot() -> None:
        # wipe storage when debug build is used on real hardware
        if not utils.EMULATOR:
            config.wipe()

        register(
            MessageType.DebugLinkDecision, protobuf_workflow, dispatch_DebugLinkDecision
        )
        register(
            MessageType.DebugLinkGetState, protobuf_workflow, dispatch_DebugLinkGetState
        )
