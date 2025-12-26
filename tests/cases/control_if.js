function classify(x) {
  var label;
  if (x > 0) {
    label = 'positive';
  } else if (x === 0) {
    label = 'zero';
  } else {
    label = 'negative';
  }
  return label;
}
