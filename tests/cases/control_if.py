def classify(x):
    label = None
    if x > 0:
        label = 'positive'
    elif x == 0:
        label = 'zero'
    else:
        label = 'negative'
    return label
