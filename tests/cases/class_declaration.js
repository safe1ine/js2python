class Person {
  constructor(name) {
    this.name = name;
  }

  greet() {
    return `Hello ${this.name}`;
  }
}

function makePerson() {
  return new Person('Alice');
}
