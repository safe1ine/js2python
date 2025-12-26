function grade(score) {
  var letter;
  switch (true) {
    case score >= 90:
      letter = 'A';
      break;
    case score >= 80:
      letter = 'B';
      break;
    case score >= 70:
      letter = 'C';
      break;
    default:
      letter = 'D';
  }
  return letter;
}
