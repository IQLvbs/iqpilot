"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""
from iqdbc.can.parser import CANParser

QUIET_NANOS = 100_000_000


class MessageSource:
  def __init__(self, name: str, parsers: list[CANParser]):
    self.name = name
    self.parsers = parsers
    self.address = parsers[0].dbc.name_to_msg[name].address
    self.active = parsers[0]

    for parser in parsers:
      parser._add_message(name)
    self.resolve()

  def last_seen(self, parser: CANParser) -> int:
    timestamps = parser.message_states[self.address].timestamps
    return timestamps[-1] if timestamps else 0

  def resolve(self) -> CANParser:
    newest = max(self.last_seen(parser) for parser in self.parsers)
    if newest - self.last_seen(self.active) > QUIET_NANOS:
      self.active = next(parser for parser in self.parsers if self.last_seen(parser) == newest)

    for parser in self.parsers:
      parser.message_states[self.address].ignore_alive = parser is not self.active

    return self.active

  def vl(self) -> dict[str, float]:
    return self.resolve().vl[self.name]
