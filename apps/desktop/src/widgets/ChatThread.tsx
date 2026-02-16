import { useEffect, useMemo, useState, type RefObject } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Copy, MoreHorizontal, ThumbsDown, ThumbsUp } from "lucide-react";
import { cn } from "../shared/utils/cn";
import type { Message } from "../shared/types/ui";
import DropdownMenu from "../shared/ui/DropdownMenu";
import IconButton from "../shared/ui/IconButton";
import { formatTime } from "../shared/utils/formatTime";
import MarkdownMessage from "./MarkdownMessage";

export type ChatThreadProps = {
  messages: Message[];
  ratings: Record<string, "up" | "down">;
  onRequestMore: (messageId: string) => void;
  onThumbUp: (messageId: string) => void;
  onThumbDown: (messageId: string) => void;
  onCopy: (messageId: string) => void;
  onRetryMessage: (messageId: string) => void;
  onTypingDone: (messageId: string) => void;
  showPendingAssistant?: boolean;
  pendingAssistantText?: string;
  onScroll?: () => void;
  scrollRef?: RefObject<HTMLDivElement | null>;
};

function userDeliveryLabel(message: Message) {
  if (message.delivery_state === "queued") return "в очереди";
  if (message.delivery_state === "sending") return "отправляется";
  if (message.delivery_state === "failed") return "не отправлено";
  return "доставлено";
}

function buildWordBoundaries(text: string): number[] {
  const boundaries: number[] = [];
  const matcher = /\S+\s*/g;
  let match = matcher.exec(text);
  while (match) {
    boundaries.push(match.index + match[0].length);
    match = matcher.exec(text);
  }
  if (!boundaries.length && text.length) {
    boundaries.push(text.length);
  }
  return boundaries;
}

export default function ChatThread({
  messages,
  ratings,
  onRequestMore,
  onThumbUp,
  onThumbDown,
  onCopy,
  onRetryMessage,
  onTypingDone,
  showPendingAssistant = false,
  pendingAssistantText = "Astra готовит ответ…",
  onScroll,
  scrollRef
}: ChatThreadProps) {
  const typingMessage = useMemo(() => {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      const message = messages[index];
      if (message.role === "astra" && message.typing) {
        return message;
      }
    }
    return null;
  }, [messages]);
  const typingWordBoundaries = useMemo(
    () => (typingMessage ? buildWordBoundaries(typingMessage.text) : []),
    [typingMessage]
  );

  const [typedWordCount, setTypedWordCount] = useState(0);

  useEffect(() => {
    setTypedWordCount(0);
  }, [typingMessage?.id]);

  useEffect(() => {
    if (!typingMessage) return;
    const totalWords = typingWordBoundaries.length;
    if (!totalWords) {
      onTypingDone(typingMessage.id);
      return;
    }
    if (typedWordCount >= totalWords) {
      onTypingDone(typingMessage.id);
      return;
    }
    const step = Math.max(1, Math.ceil(totalWords / 180));
    const timer = window.setTimeout(() => {
      setTypedWordCount((value) => Math.min(totalWords, value + step));
    }, 24);
    return () => window.clearTimeout(timer);
  }, [onTypingDone, typedWordCount, typingMessage, typingWordBoundaries]);

  return (
    <div className="chat-thread" onScroll={onScroll} ref={scrollRef}>
      <AnimatePresence mode="popLayout">
        {messages.map((message) => {
          const isUser = message.role === "user";
          const rating = ratings[message.id];
          const isTyping = !isUser && typingMessage?.id === message.id && message.typing;
          const visibleWords = Math.max(1, typedWordCount);
          const cutoff =
            isTyping && typingWordBoundaries.length
              ? typingWordBoundaries[Math.min(visibleWords, typingWordBoundaries.length) - 1] || 0
              : message.text.length;
          const typingText = isTyping ? message.text.slice(0, cutoff) : message.text;
          return (
            <motion.div
              key={message.id}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.16 }}
              className={cn("chat-message", {
                "is-user": isUser,
                "is-assistant": !isUser
              })}
            >
              <div className="chat-bubble">
                {isUser ? (
                  <div className="chat-plain-text">{message.text}</div>
                ) : isTyping ? (
                  <div className="chat-typing">
                    <MarkdownMessage text={typingText} preview />
                    <button
                      type="button"
                      className="chat-typing-skip"
                      onClick={() => setTypedWordCount(typingWordBoundaries.length)}
                    >
                      Допечатать
                    </button>
                  </div>
                ) : (
                  <MarkdownMessage text={message.text} />
                )}
              </div>
              <div className="chat-meta">
                <span>
                  {isUser ? "Вы" : "Astra"}
                  {message.ts ? ` · ${formatTime(message.ts)}` : ""}
                  {isUser ? ` · ${userDeliveryLabel(message)}` : ""}
                </span>
                {isUser && message.delivery_state === "failed" ? (
                  <div className="chat-message-actions">
                    <button type="button" className="chat-retry-link" onClick={() => onRetryMessage(message.id)}>
                      Повторить
                    </button>
                  </div>
                ) : null}
                {!isUser ? (
                  <div className="chat-message-actions">
                    <IconButton
                      type="button"
                      aria-label="Скопировать"
                      size="sm"
                      onClick={() => onCopy(message.id)}
                    >
                      <Copy size={16} />
                    </IconButton>
                    <div className="chat-rating">
                      <IconButton
                        type="button"
                        aria-label="Полезно"
                        size="sm"
                        active={rating === "up"}
                        onClick={() => onThumbUp(message.id)}
                      >
                        <ThumbsUp size={16} />
                      </IconButton>
                      <IconButton
                        type="button"
                        aria-label="Не полезно"
                        size="sm"
                        active={rating === "down"}
                        onClick={() => onThumbDown(message.id)}
                      >
                        <ThumbsDown size={16} />
                      </IconButton>
                    </div>
                    <DropdownMenu
                      align="right"
                      width={200}
                      items={[
                        {
                          id: "more",
                          label: "Попросить подробнее",
                          onSelect: () => onRequestMore(message.id)
                        }
                      ]}
                      trigger={({ toggle }) => (
                        <IconButton type="button" aria-label="Еще" size="sm" onClick={toggle}>
                          <MoreHorizontal size={16} />
                        </IconButton>
                      )}
                    />
                  </div>
                ) : null}
              </div>
              {isUser && message.error_detail ? <div className="chat-error-detail">{message.error_detail}</div> : null}
            </motion.div>
          );
        })}
        {showPendingAssistant ? (
          <motion.div
            key="pending-assistant"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.16 }}
            className="chat-message is-assistant is-pending"
          >
            <div className="chat-bubble">
              <div className="chat-pending">
                <span className="chat-pending-label">{pendingAssistantText}</span>
                <span className="chat-pending-dots" aria-hidden="true">
                  <span />
                  <span />
                  <span />
                </span>
              </div>
            </div>
            <div className="chat-meta">
              <span>Astra · сейчас</span>
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}
