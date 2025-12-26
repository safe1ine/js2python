'use strict';

function greet(name) {
  if (!name) {
    return 'Hello, Stranger';
  }
  return 'Hello, ' + name;
}

const toUpper = (value = '') => value.toUpperCase();

const safeDivide = (a, b = 1) => {
  if (b === 0) {
    throw new Error('Cannot divide by zero');
  }
  return a / b;
};

const logger = (...args) => console.log.apply(console, args);

class Reporter {
  static headers() {
    return ['name', 'score'];
  }

  constructor(data) {
    this.data = data;
  }

  summary() {
    return this.data.map((item) => `${item.name}: ${item.score}`);
  }
}

function buildData(seed) {
  let total = 0;
  const records = [];

  for (let i = 0; i < seed.length; i += 1) {
    const entry = seed[i];
    total += entry.score;
    records.push({ name: entry.name, score: entry.score });
  }

  let average = 0;
  if (seed.length > 0) {
    average = total / seed.length;
  }

  const stats = {
    total,
    average,
  };

  return { records, stats };
}

function classifyScore(score) {
  switch (true) {
    case score >= 90:
      return 'A';
    case score >= 80:
      return 'B';
    case score >= 70:
      return 'C';
    default:
      return 'D';
  }
}

function summarize(seed) {
  const prepared = buildData(seed);
  const report = new Reporter(prepared.records);

  const grades = [];
  for (const record of prepared.records) {
    grades.push({ name: record.name, grade: classifyScore(record.score) });
  }

  const indices = [];
  for (const key in prepared.stats) {
    if (Object.prototype.hasOwnProperty.call(prepared.stats, key)) {
      indices.push(`${key}:${prepared.stats[key]}`);
    }
  }

  let attempts = 0;
  while (attempts < 3) {
    logger('Attempt', attempts + 1, 'summary ready');
    attempts += 1;
  }

  try {
    const lines = report.summary();
    const headline = Reporter.headers().join(', ');
    return {
      headline,
      lines,
      indices,
      grades,
      upperNames: seed.map((entry) => toUpper(entry.name)),
      safeDiv: safeDivide(prepared.stats.total, seed.length || 1),
    };
  } catch (err) {
    logger('Failed to summarize:', err.message);
    throw err;
  } finally {
    logger('Summary finished');
  }
}

const sample = [
  { name: 'Alice', score: 95 },
  { name: 'Bob', score: 82 },
  { name: 'Cara', score: 76 },
];

if (require.main === module) {
  const result = summarize(sample);
  logger('Result headline:', result.headline);
  logger('Lines:', result.lines.join('; '));
  logger('Indices:', result.indices.join('; '));
  logger('Grades:', result.grades.map((g) => `${g.name}:${g.grade}`).join('; '));
  logger('Upper:', result.upperNames.join(', '));
  logger('Safe divide:', result.safeDiv);
}

module.exports = {
  greet,
  toUpper,
  safeDivide,
  buildData,
  classifyScore,
  summarize,
};
