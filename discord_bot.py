import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
import functools
import os
import sys
import traceback

import codesynth
import discord
import random

discord_token = os.environ['DISCORD_TOKEN']

def list_randshrink(list, count):
    result = [item for item in list]
    for idx in range(count):
        result.pop(random.randint(0, len(result)-1))
    return result

def asyncify(func):
    def asynced(*params, **kwparams):
        return asyncio.get_running_loop().run_in_executor(None, functools.partial(func, **kwparams), *params)
    return asynced

class emoji:
    thumbsup = '👍'
    thumbsdown = '👎'
    smiley = '😃'
    poop = '💩'
    plusone = thumbsup + smiley
    minusone = thumbsdown

class Channel:
    def __init__(self, channel):
        self.maxscore = 0
        self.channel = channel
        self.pending = []
        self.history = []
        self.can_talk = False
        self.boringness = 0
        self.timemark = datetime.now()

class Bot:
    def __init__(self, token):
        self.client = discord.Client()
        self.client.event(self.on_ready)
        self.client.event(self.on_message)
        self.client.event(self.on_raw_reaction_add)
        self.client.event(self.on_raw_reaction_remove)
        self.token = token

        self.channels = {}
        self.new_messages = asyncio.Event()
        self.start_replying = asyncio.Event()

    @property
    def name(self):
        return str(self.client.user).split('#')[0]

    async def fill_history(self):
        await asyncio.sleep(0)
        ct = 0
        for name, channel in self.channels.items():
            if len(channel.pending):
                while len(channel.pending):
                    ct += 1
                    msg = channel.pending.pop(0)
                    if msg.content.strip():
                        #print('adding to history:', msg.author, msg.content)
                        if not channel.can_talk and (self.name + ', you can talk') in msg.content:
                            channel.can_talk = True
                        elif channel.can_talk and (self.name + ', stop talking') in msg.content:
                            channel.can_talk = False
                        channel.history.append(msg)
                if len(channel.history) > 2048:
                    channel.history = channel.history[-2048:]
        return ct

    def run(self):
        loop = self.client.loop
        async def do_loop():
            try:
                await asyncio.gather(self.client.start(self.token), self.pump())
            except:
                await self.client.close()
                raise
        try:
            loop.run_until_complete(do_loop())
        finally:
            loop.close()

    async def on_ready(self):
        print('We have logged in as {0.user}'.format(self.client))
        for channel in self.client.get_all_channels():
            print('channel:', channel)
            if type(channel) is discord.TextChannel:
                messages = []
                async for message in channel.history(limit=1024, oldest_first=False):
                    messages.insert(0, message)
                for message in messages:
                    #print(channel, message.channel, message.author, message.content)
                    await self.on_message(message)
            sys.stdout.flush()
        #self.nonself_end_of_line_token = self.usr2history(self.client.user)
        self.start_replying.set()

    async def delmsg(self, message):
        if not isinstance(message, discord.DeletedReferencedMessage):
            for channel in self.channels.values():
                if channel.channel == message.channel:
                    try:
                        channel.history.remove(message)
                    except:
                        try:
                            channel.pending.remove(message)
                        except:
                            pass
                    break
            message.content = ''
            await message.delete()

    async def preprocess_message(self, message):
        return True
    
    async def on_message(self, message):
        print(message.channel, message.author, 'in response to =', message.reference, ':', message.content)
        if await self.preprocess_message(message):
            channel = self.channels.setdefault(message.channel, Channel(message.channel))
            channel.pending.append(message)
            channel.boringness = 0
        self.new_messages.set()
        sys.stdout.flush()

    async def on_raw_reaction_add(self, payload):
        self.new_messages.set()

    async def on_raw_reaction_remove(self, payload):
        self.new_messages.set()
        print('reaction', str(payload.emoji))

class bot(Bot):
    def __init__(self, token, model):
        super().__init__(token)
        self.model = model

    def msgscore(self, msg):
        score = 0
        for reaction in msg.reactions:
            if str(reaction.emoji) in emoji.plusone:
                score += reaction.count
            elif str(reaction.emoji) in emoji.minusone:
                score -= reaction.count
        return score
    def scorestr(self, score):
        if score < 0:
            str = 'bad'
        elif score > 0:
            str = 'good'
        else:
            str = 'soso'
        return f'{str} {score}'

    def isscorestr(self, scorestr):
        parts = scorestr.split(' ')
        return len(parts) == 2 and parts[0] in ('bad','good','soso') and (parts[1].isnumeric() or parts[1][0] == '-' and parts[1][1:].isnumeric())

    def filtercontent(self, content):
        replacement = content.find('{replaced from:')
        if replacement >= 0:
            content = content[:replacement]
        return content

    def msg2history(self, msg, chandata):
        botstr = '(bot)' if msg.author.bot else '(human)'
        content = self.filtercontent(msg.content)
        return f'{msg.author} {botstr}: {self.scorestr(self.msgscore(msg))}: {msg.created_at.isoformat(" ", "milliseconds")} {content}'
    def usr2history(self, user, chandata = None):
        botstr = '(bot)' if user.bot else '(human)'
        score = self.scorestr(chandata.maxscore) if chandata is not None else ''
        return f'{user} {botstr}: {score}: '

    async def pump(self):
        #print('pump out start')
        await self.start_replying.wait()
        while True:
            #print('pump out loop')
            found = await self.fill_history()
            for channel, chandata in [*self.channels.items()]:
                #print(channel, 'talk =', talk, 'len(history) =', len(history))
                #if chandata.can_talk:
                #    print(channel, 'score of last message =', self.msgscore(chandata.history[-1]))
                if chandata.can_talk and (
                    chandata.history[-1].author != self.client.user or
                    self.msgscore(chandata.history[-1]) < 0
                ) and chandata.boringness < 128:
                    #print('responding to', history[-1].author, history[-1].content)
                    found = True
                    reply_datetime = datetime.now()
                    try:
                        removect = 0
                        await self.fill_history()
                        prompt = '\n'.join([self.msg2history(msg, chandata) for msg in list_randshrink(chandata.history[-1024:], removect)])
                        if '(human)' not in prompt:
                            continue
                        chandata.maxscore = max(0,max((self.msgscore(msg) for msg in chandata.history[-16:])))
                        preprompt = '\n' + self.usr2history(self.client.user, chandata).strip()
                        prompt += preprompt
                        model_kwparams = dict(
                            #eos_token_id=self.nonself_end_of_line_token,
                            return_full_text=False,
                            max_new_tokens=512,
                            #top_p=0.25
                            #temperature=1.0
                        )
                        #print(model_kwparams)
                        sys.stdout.flush()
                        if (chandata.timemark - datetime.now()).total_seconds() <= 10:
                            print('typing since, given now is', datetime.now(), 'then timemark is soon:', chandata.timemark)
                            async with channel.typing():
                                reply = await asyncify(self.model)(prompt.strip(), **model_kwparams)
                        else:
                            reply = await asyncify(self.model)(prompt.strip(), **model_kwparams)
                        reply = reply[0]['generated_text'].strip()
                        print(prompt[-256:])
                        print('considering:', preprompt + ' ' + reply)
                        date, time, reply = reply.split(' ', 2)
                        try:
                            reply_datetime = datetime.fromisoformat(date  + ' ' + time)
                        except ValueError as e:
                            print(e)
                            continue
                        print('time =', reply_datetime.isoformat())
                        #time = datetime.datetime.fromisoformat(date + ' ' + time)
                        lines = reply.split('\n')
                        # quick fix: remove items from prompt to change context
                        if removect < len(chandata.history):
                            removect += 1

                       # if '(human)' not in lines[1] and '(human)' not in lines[2]:
                       #     reply = '' #'!' + reply
                       #     lines = ['']
                        #elif '(human)' not in lines[1]:
                        #    reply = '!' + reply

                        # for multiline: read up until another message is expected
                        reply = ''
                        humanct = 0
                        botct = 0
                        mark = 0
                        for idx, line in enumerate(lines):
                            if '#' in line: # hacky way to identify that a line is message
                                name, bit = line.split('#', 1)
                                if ':' in bit:
                                    bits = bit.split(':')
                                    namebits = bits[0].split(' ')
                                    if len(namebits) == 2 and len(bits) > 2 and namebits[0].isnumeric() and namebits[1] in ('(bot)', '(human)') and self.isscorestr(bits[1].strip()):
                                        if mark == 0:
                                            mark = idx
                                        if '(human)' not in line:
                                            botct += 1
                                        else:
                                            humanct += 1
                                        if botct + humanct < 3:
                                            break
                        if humanct > 0:
                            reply = '\n'.join(lines[:mark])
                    except Exception as e:
                        print(reply)
                        reply = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
                    if len(reply) == 0:
                        reply = '[empty message??]'
                        print(reply)
                        reply = ''
                        chandata.boringness += 1
                    sys.stdout.flush()
                    if len(reply) > 0:
                        delay = (reply_datetime - datetime.now()).total_seconds()
                        if delay > 10:
                            chandata.timemark = reply_datetime
                            print('too far in future to wait here for, moving on', delay, 'to', chandata.timemark)
                            sys.stdout.flush()
                            continue
                        elif delay > 0:
                            if delay > 1:
                                await asyncio.sleep(delay - 1)
                                delay = 1
                            async with channel.typing():
                                await asyncio.sleep(delay)
                        await channel.send(reply)
            if not found:
                self.new_messages.clear()
                await self.new_messages.wait()

    async def preprocess_message(self, message):
        is_bot_reply = False
        if message.reference is not None and message.reference.resolved is not None and not isinstance(message.reference.resolved, discord.DeletedReferencedMessage) and message.reference.resolved.author == self.client.user:
            is_bot_reply = True
            if (message.content.startswith(f'{self.name}, replace with:') or message.content.lower().startswith('replace:')):
                newcontent = message.content[len(message.content.split(':', 1)[0]) + 2:].strip()
                oldcontent = message.reference.resolved.content
                while '{replaced from: ' in oldcontent:
                    oldcontent = oldcontent[oldcontent.find('{replaced from: ') + len('{replaced from: '):]
                    oldconent = oldcontent[:-1]
                await message.reference.resolved.edit(content = newcontent + '{replaced from: ' + oldcontent + '}' )
                print('UPDATED CONTENT:', message.reference.resolved.content)
                sys.stdout.flush()
                return False
            elif (message.content.lower().startswith(f'{self.name}, delete') or message.content.lower().strip() == 'delete'):
                print('DELETE')
                sys.stdout.flush()
                await self.delmsg(message.reference.resolved)
                return False
        if is_bot_reply: # could also check for name mention
            if message.content.lower().startswith('ctx '):
                _, name, cmd, *params = message.content.split(' ', 3)
        return True

    async def on_raw_reaction_add(self, payload):
        if str(payload.emoji) == emoji.poop:
            for channel, chandata in [*self.channels.items()]:
                if channel.id == payload.channel_id:
                    for message in (*chandata.pending, *chandata.history):
                        if message.id == payload.message_id:
                            await self.delmsg(message)
                            break
        return await super().on_raw_reaction_add(payload)

#model = codesynth.ai21_jumbo()
model = codesynth.multi_demo(codesynth.eleuther_demo(), codesynth.bellard_demo())
#model = codesynth.openai()
if __name__ == '__main__':
    bot(discord_token, model).run()

