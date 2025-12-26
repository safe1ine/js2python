function risky(fn) {
  try {
    return fn();
  } catch (err) {
    console.log(err.message);
    throw err;
  } finally {
    console.log('cleanup');
  }
}
