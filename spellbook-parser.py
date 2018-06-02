#! /usr/bin/python
from __future__ import print_function
from collections import defaultdict
import sys
import re
import csv

def check_all(check_funcs, value):
	return reduce(lambda acc, func: acc and func(value), check_funcs, False)

def check_any(check_funcs, value):
	return reduce(lambda acc, func: acc or func(value), check_funcs, False)

drop_regex = re.compile('|'.join(
	map(lambda s: '(?:'+s+')',[
		'^CHAPTER [0-9]+',
		'^SPELLS?$',
		'^DESCRIPTIONS?$',
		'^SPELL DESCRIPTIONS$',
		'^SPELL LISTS$',
		'^MAGIC$',
	])
))
drop_rules_given_strip = [
	lambda s: re.match(drop_regex, s) is not None
]
drop_rules = [
	lambda line: check_any(drop_rules_given_strip, line.strip()), 
]

schools = [
	'Abjuration',
	'Conjuration',
	'Divination',
	'Enchantment',
	'Evocation',
	'Illusion',
	'Necromancy',
	'Transmutation',
	'Universal'
]

schools_startswith_regex = re.compile('^'+'|'.join(schools))

level_str = 'Level:'

def build_raw_dict(first_page, is_multiline_allcaps):
	page_num = first_page
	candidate = 0
	current_spell_and_page = (None, -1)
	prev_lines = []
	raw_spells = {}
	failures = []

	for line in sys.stdin:
		if line.startswith(''):
			page_num += 1
			line = line[1:]

		if check_any(drop_rules, line) or line.strip() == str(page_num):
			continue

		if line.startswith(level_str):
			if is_multiline_allcaps:
				# some books list spells on multiple lines (Spell Compendium)
				# and even omit the school classification occasionally.
				# this is hard to parse out in general, but thankfully they also
				# use all-caps spell names, which makes it easier to distinguish

				def is_spell_name_part(string):
					return string.isupper() and '.' not in string

				new_lines = []
				for prev in reversed(prev_lines):
					if is_spell_name_part(prev):
						break;
					new_lines.insert(0, prev_lines.pop())

				new_spell_name = ''
				for prev in reversed(prev_lines):
					if is_spell_name_part(prev):
						new_spell_name = prev_lines.pop() + new_spell_name
					else:
						break

				if new_spell_name == '':
					failures.append((ValueError('unable to find spell name'),
						{'after:':list(new_lines),
						'before:':list(prev_lines)}))
			else:
				# most source books list spells on a single line and always
				# have a school classification

				new_lines = []
				for prev in reversed(prev_lines):
					new_lines.insert(0, prev_lines.pop())
					if re.match(schools_startswith_regex, prev):
						break

				new_spell_name = prev_lines.pop()

			(current_spell_name, spell_page) = current_spell_and_page
			raw_spells[current_spell_name] = (spell_page, prev_lines)
			current_spell_and_page = (new_spell_name, page_num)
			prev_lines = new_lines
		
		prev_lines.append(line)

	return (raw_spells, failures)

newline_regex = re.compile('(.)\n+(.)|$')
def remove_newlines(string):
	def replace_newline(regex_match):
		(char_before, char_after) = regex_match.group(1, 2)
		if not char_after:
			# newline before end of string, just truncate it
			return char_before
		if char_before == '-':
			# hyphenated break. somtimes continuing a word (e.g. conti-\nnuing)
			# but counter examples exist like Mind-\nAffecting
			# best hueristic is to say that caps letter after is the exception
			if char_after.isupper():
				return char_before+char_after
			else:
				return char_after
		# otherwise replace with space
		return char_before + ' ' + char_after

	return re.sub(newline_regex, replace_newline, string) if string else None

school_str = 'School:'
type_str = 'Type:'
school_match_regex = re.compile(
	# group the school and the subschool together
	'(?P<school>'
	# all schools in an | 'or' match
	'(?:'+'|'.join(schools)+')'
	# the possible subschool in a parenthetical
	'(?:\s*\([^\)]+\))?'
	')' # close 'school' group
	# followed by a possible type descriptor in square brackets
	'(?:\s*\[(?P<type>[^\]]+)\])?'
	# must be followed on the next line by the level string.
	# otherwise it's possible for the regex to continue scanning into the text
	'\s+'+level_str
)
def extract_school(line, fields_dict):
	match = re.match(school_match_regex, line)
	if not match:
		return line
	groups = match.groupdict()
	fields_dict[school_str] = remove_newlines(groups['school'])
	fields_dict[type_str] = remove_newlines(groups['type'])
	return line[line.index(level_str):]

replace_class_name = {
	'Brd':'Bard',
	'Clr':'Cleric',
	'Drd':'Druid',
	'Pal':'Paladin',
	'Rgr':'Ranger',
	'Sor/Wiz':'Sorcerer/Wizard',
}
def normalize_class_name(class_name):
	return remove_newlines(replace_class_name.get(class_name, class_name)).title()

level_split_regex = re.compile(
	# the regex is applied repeatedly after timming off the front fo the string.
	# as a result, the start may have the comma and separator from the previous entry.
	# strip those off by matching before the group
	'(?:,\s+)?'
	# capture the class and level in a group
	'(?P<class>'
	# class name. includes '/' e.g. 'Sor/Wiz', '-' for line break hyphenation,
	# whitespace e.g. 'psychic warrior'
	'[A-Za-z][A-Za-z/\-\s]*' 
	')'# close the class group
	# a single space and one digit follows (assuming no spells >9)
	'\s(?P<level>[0-9])'
	# some classes are then qualified in a parenthetical, e.g. Druid 4 (Gatekeeper)
	'(?P<paren>\s\([^\)]+\))?'
)
def extract_level(line, fields_dict):
	# trim off 'Level: ' from the start
	line = line.split(level_str+' ')[1]
	classes_by_level = defaultdict(list)
	while True:
		match = re.match(level_split_regex, line)
		if not match:
			break
		line = line[match.end():]
		groups = match.groupdict()
		level = int(groups['level'])
		cls = groups['class'] + (groups['paren'] or '')
		cls = normalize_class_name(cls)
		classes_by_level[level].append(cls)
	fields_dict[level_str] = classes_by_level
	return line

def normalize_spell_name(string):
	return remove_newlines(string.strip()).title()

text_str = 'Text:'
page_str = 'Page:'

def paren_regex(s):
	return re.compile('('+s+')')

fields_delim_regex = map(lambda x: x if isinstance(x, tuple) else (x, paren_regex('\n'+x)), [
	# don't match regex against Material Components or Verbal Components
	('Component(s):',paren_regex('\nComponents?:')),
	'Casting Time:',
	'Range:',
	('Target(s):',paren_regex('\n(?:Area\sor\s)?Targets?:')),# these are pretty crap special cases.
	('Effect:',paren_regex('\n(?:Target(?:\sand\s)|/)?Effect:')), # the right thing to do is compound the fields
	('Area:',paren_regex('\n(?:(?:Effect\sand\s)|(?:Target,\sEffect,\sor\s))?Area:')), # more generally, but this will do for now
	'Duration:',
	'Saving Throw:',
	'Spell Resistance:',
	# the descriptive text always begins with a capital letter (or a quote) after all the previous fields.
	# it's not a perfect identification scheme, but it "works" enough
	('Text:',paren_regex('\n(?="?[A-Z])')),
])
def organize(raw_spells):
	spells = {}
	failures = []
	for (spell_name, (page_num, lines)) in raw_spells.iteritems():
		if not spell_name:
			continue
		spell_name = normalize_spell_name(spell_name)
		fields = {page_str:page_num}
		line = ''.join(lines)

		try:
			line = extract_school(line, fields)
			line = extract_level(line, fields)
			field = None # this is a sentinel which should technically have no value
			# it would only be populated if the first extraction left something
			for (delim, regex) in fields_delim_regex:
				split = re.split(regex, line, maxsplit=1)
				if len(split) > 2:
					field_value = split[0]
					line = split[2]
					fields[field] = remove_newlines(field_value.strip())
					field = delim

			fields[field] = remove_newlines(line.strip())
		except BaseException as e:
			raise
			failures.append((e, spell_name, lines, fields))
			continue

		spells[spell_name] = fields

	return (spells, failures)

def dump_tsv(spells, source_book):
	writer = csv.writer(sys.stdout, delimiter='\t')
	header = [
		'Spell:',
		school_str,
		type_str,
		'Class:',
		'Lvl:'
	]
	for (field, _) in fields_delim_regex:
		header.append(field)

	header.append('Source:')
	header.append('Page:')

	writer.writerow(header)
	
	for spell, fields in sorted(spells.iteritems()):
		for level, classes in fields[level_str].iteritems():
			row = [
				spell,
				fields.get(school_str, ''),
				fields.get(type_str, ''),
				', '.join(classes),
				level
			]
			for (field, _) in fields_delim_regex:
				row.append(fields.get(field, ''))
			row.append(source_book)
			row.append(fields[page_str])
			writer.writerow(row)


def errprint(*args, **kwargs):
	print(*args, file=sys.stderr, **kwargs)

def main():
	#TODO import argparse
	source_book = sys.argv[1]
	starting_page = int(sys.argv[2])
	is_multiline_allcaps = sys.argv[3] != '0'
	(raw_spells, failures) = build_raw_dict(starting_page, is_multiline_allcaps)
	(spells, more_failures) = organize(raw_spells)
	failures += more_failures

	dump_tsv(spells, source_book)

	if failures:
		errprint('Failed to make sense of the following entries:')
		for failure in failures:
			errprint(failure)


if __name__ == '__main__':
	main()
