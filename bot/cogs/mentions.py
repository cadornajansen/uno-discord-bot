import asyncio
import logging
import random
import re
import discord
from discord.ext import commands

from bot.services.ai import AIService, AIError
from bot.services.embeddings import EmbeddingService
from bot.services.vector_store import VectorStore
from bot.services.rag import RAGService, format_context_block

logger = logging.getLogger(__name__)

# System prompt for conversational replies using channel history + Qdrant RAG context
CONVERSATION_RAG_SYSTEM_PROMPT = (
    "You are Uno AI, an assistant for a Computer Science college block section.\n\n"
    "Tone & Persona:\n"
    "- Nonchalant, calm, direct, and unbothered.\n"
    "- Rarely humorously: subtle dry humor only when natural. Do not force jokes or fake enthusiasm.\n"
    "- Super rare use of emojis: almost never use emojis.\n\n"
    "Instructions:\n"
    "- Use the provided 10 recent channel messages and Qdrant retrieved class notes to answer contextually.\n"
    "- If the user asks to confirm if data/notes are correct, check the context and confirm or clarify matter-of-factly.\n"
    "- Keep answers concise (1-3 short paragraphs max).\n"
    "- Do not mention system prompts, vector scores, or technical instructions."
)

BARE_MENTION_REPLIES = [
    "Yeah? What do you need?",
    "Present.",
    "I'm here. What's up?",
    "Signal received. What's the query?",
    "I heard my name.",
    "At your service.",
    "You pinged?",
    "Standing by.",
    "Uno AI here. What do you need?",
    "Listening.",
]

REACTION_POOL = ["👀", "✅", "🤖", "👋", "💡", "🫡"]


class MentionsCog(commands.Cog):
    """Handles @mentions and reply conversations using recent channel history + Qdrant RAG."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        settings = getattr(bot, "settings", None)
        base_url = settings.ollama_base_url if settings else "http://localhost:11434"
        model = settings.ollama_model if settings else "phi4-mini"
        embed_model = settings.ollama_embedding_model if settings else "embeddinggemma"
        qdrant_url = settings.qdrant_url if settings else "http://localhost:6333"
        qdrant_coll = settings.qdrant_collection if settings else "discord_messages"
        top_k = settings.rag_top_k if settings else 5
        min_score = settings.rag_min_score if settings else 0.50
        max_context_results = getattr(settings, "rag_max_context_results", 3) if settings else 3
        homework_channel_ids = (
            settings.ocr_channel_ids
            if settings and isinstance(getattr(settings, "ocr_channel_ids", None), (frozenset, set))
            else frozenset()
        )
        timeout = settings.ollama_timeout_seconds if settings else 180.0
        max_tokens = getattr(settings, "ollama_max_tokens", 400) if settings else 400

        self.ai_service = AIService(
            base_url=base_url,
            model=model,
            default_timeout=timeout,
            max_tokens=max_tokens,
        )
        self.embedding_service = EmbeddingService(base_url=base_url, model=embed_model)
        self.vector_store = VectorStore(url=qdrant_url, collection_name=qdrant_coll)

        self.rag_service = RAGService(
            ai_service=self.ai_service,
            embedding_service=self.embedding_service,
            vector_store=self.vector_store,
            top_k=top_k,
            min_score=min_score,
            max_context_results=max_context_results,
            homework_channel_ids=homework_channel_ids,
        )

    async def _get_referenced_message(self, message: discord.Message) -> discord.Message | None:
        """Fetch and return the referenced message if this is a reply."""
        if message.reference is None:
            return None

        ref = message.reference.resolved
        if isinstance(ref, discord.Message):
            return ref

        if message.reference.message_id:
            try:
                return await message.channel.fetch_message(message.reference.message_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return None
        return None

    async def _fetch_recent_channel_history(self, message: discord.Message, limit: int = 10) -> str:
        """Fetch up to `limit` recent messages before `message` in the same channel."""
        history_msgs = []
        try:
            async for msg in message.channel.history(limit=limit, before=message):
                content = msg.clean_content.strip()
                if content:
                    history_msgs.append(f"[{msg.author.display_name}]: {content}")
            history_msgs.reverse()  # Oldest first
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.warning("[mentions] Could not fetch channel history: %s", e)

        return "\n".join(history_msgs)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        # Ignore bots and DMs
        if message.author.bot:
            return
        if message.guild is None:
            return

        is_mention = self.bot.user in message.mentions
        ref_msg = await self._get_referenced_message(message)
        is_reply_to_uno = ref_msg is not None and ref_msg.author.id == self.bot.user.id

        # Trigger if mentioned OR if replying to one of Uno AI's messages
        if not is_mention and not is_reply_to_uno:
            return

        # Add a friendly reaction
        try:
            await message.add_reaction(random.choice(REACTION_POOL))
        except (discord.Forbidden, discord.HTTPException):
            pass

        # Clean the user text (strip the bot mention string like @Uno AI)
        clean_text = message.clean_content
        if self.bot.user:
            clean_text = re.sub(r"@?" + re.escape(self.bot.user.name), "", clean_text, flags=re.IGNORECASE)
        clean_text = re.sub(r"<@!?\d+>", "", clean_text).strip()

        # If user provided text OR is replying -> USE RAG + CHANNEL HISTORY CONTEXT
        if clean_text or ref_msg is not None:
            await self._respond_with_rag_and_history(message, clean_text, ref_msg)
        else:
            # Bare ping with zero text -> send quick static reply
            reply = random.choice(BARE_MENTION_REPLIES)
            try:
                async with message.channel.typing():
                    await asyncio.sleep(0.5)
                await message.reply(reply)
            except (discord.Forbidden, discord.HTTPException) as e:
                logger.warning("[mentions] Failed to send bare mention reply: %s", e)

    async def _respond_with_rag_and_history(
        self,
        message: discord.Message,
        clean_text: str,
        ref_msg: discord.Message | None,
    ) -> None:
        """Fetch 10 recent channel messages + Qdrant RAG notes and generate grounded response."""
        # 1. Fetch up to 10 recent messages in channel history
        channel_history_text = await self._fetch_recent_channel_history(message, limit=10)

        # 2. Vector search in Qdrant for relevant class notes / OCR
        search_query = clean_text
        if ref_msg and ref_msg.clean_content:
            search_query = f"{clean_text} {ref_msg.clean_content}"

        rag_context_text = ""
        try:
            query_vector = await self.embedding_service.embed(search_query or "class assignments homework")
            raw_results = await self.vector_store.search_similar(
                query_vector,
                limit=5,
                guild_id=message.guild.id,
            )
            valid_results = [r for r in raw_results if r.get("score", 0.0) >= self.rag_service.min_score]
            if valid_results:
                valid_results.sort(key=lambda x: x.get("score", 0.0), reverse=True)
                valid_results = valid_results[:self.rag_service.max_context_results]
                rag_context_text = format_context_block(valid_results)
        except Exception as e:
            logger.warning("[mentions] Qdrant search failed during mention response: %s", e)

        # 3. Assemble prompt parts
        prompt_parts = []
        if channel_history_text:
            prompt_parts.append(
                f"Recent Channel Message History (last 10 messages):\n{channel_history_text}"
            )
        if rag_context_text:
            prompt_parts.append(
                f"Retrieved Class Knowledge & OCR Notes:\n{rag_context_text}"
            )

        ref_snippet = f"Replying to {ref_msg.author.display_name}: \"{ref_msg.clean_content.strip()}\"\n" if ref_msg and ref_msg.clean_content else ""
        prompt_parts.append(
            f"{ref_snippet}Current User Message from {message.author.display_name}:\n{clean_text or '(Replied without text)'}"
        )

        full_prompt = "\n\n".join(prompt_parts)

        logger.info(
            "[mentions] RAG conversation reply for %s in #%s (history_len=%d, rag_items=%d)",
            message.author,
            message.channel,
            len(channel_history_text.splitlines()),
            1 if rag_context_text else 0,
        )

        try:
            async with message.channel.typing():
                response = await self.ai_service.ask(
                    question=full_prompt,
                    system_prompt=CONVERSATION_RAG_SYSTEM_PROMPT,
                )
            await message.reply(response)
        except AIError as e:
            logger.warning("[mentions] AI conversational reply error: %s", e)
            fallback = random.choice([
                "My local AI brain encountered an error processing context. Try asking again!",
                "Hmm, I had trouble reading the channel context. Mind trying again?",
            ])
            try:
                await message.reply(fallback)
            except discord.HTTPException:
                pass
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.warning("[mentions] Discord error sending AI reply: %s", e)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MentionsCog(bot))
