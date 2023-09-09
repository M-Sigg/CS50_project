import os

from flask import Flask, flash, redirect, render_template, request, session , url_for, send_file
from flask_session import Session
from flask_sqlalchemy import SQLAlchemy
from tempfile import mkdtemp
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime
from dotenv import load_dotenv
import psycopg2
import psycopg2.extras

import yfinance as yf

# 
import numpy as np
import pandas as pd
from io import BytesIO
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
import matplotlib.pyplot as plt
plt.style.use('ggplot')
plt.switch_backend('Agg')
import base64

# Portfolio Opt
from pypfopt.efficient_frontier import EfficientFrontier
from pypfopt import risk_models
from pypfopt import expected_returns
from pypfopt.discrete_allocation import DiscreteAllocation, get_latest_prices


from helpers import login_required, lookup, usd


# load the .env file
load_dotenv()

# Configure application
app = Flask(__name__)

# Costum filter
app.jinja_env.filters["usd"] = usd


# Configure session to use filesystem (instead of signed cookies)
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_TYPE'] = 'filesystem'
Session(app)


# Database
url = os.getenv("DATABASE_URL")
connection = psycopg2.connect(url)

# Setup tables
with connection:
    with connection.cursor() as cursor:
        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS users (
                        id SERIAL PRIMARY KEY NOT NULL,
                        username TEXT NOT NULL, 
                        hash TEXT NOT NULL, 
                        cash NUMERIC NOT NULL DEFAULT 10000.00
                        );
                    """)

#with connection:
 #   with connection.cursor() as cursor:
  #      cursor.execute("""
   #                    CREATE UNIQUE INDEX username On users (username);
     #               """)

with connection:
    with connection.cursor() as cursor:
        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS transactions (
                       transaction_id SERIAL PRIMARY KEY NOT NULL,
                       user_id INTEGER NOT NULL, 
                       action TEXT NOT NULL,
                       symbol TEXT NOT NULL,
                       shares INTEGER NOT NULL,
                       price REAL NOT NULL,
                       datetime TIMESTAMP,
                       FOREIGN KEY (user_id) REFERENCES users(id)
                        );
                    """)
        
with connection:
    with connection.cursor() as cursor:
        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS balance (
                       user_id INTEGER NOT NULL,
                       symbol TEXT NOT NULL, 
                       shares INTEGER NOT NULL,
                       total_value REAL NOT NULL,
                       FOREIGN KEY (user_id) REFERENCES users(id)
                        );
                    """)


@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response

@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""

    # get stocks held by user
    with connection:
        with connection.cursor(cursor_factory = psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute(
                "SELECT * FROM balance WHERE user_id = %s;", 
                [
                    session["user_id"]
                ]
            )
            stocks = cursor.fetchall()

    # create array to loop through in index.html
    display_stocks = []
    total_total = 0
    for stock in stocks:
        symbol = (stock['symbol']).upper()
        name = lookup(stock['symbol'])['name']
        shares = stock['shares']
        price = lookup(stock['symbol'])['price']
        total_value = stock['total_value']
        total_total += float(stock['total_value'])
        display_stocks.append({'symbol': symbol,
                            'name': name,
                            'shares': shares,
                            'price': usd(price),
                            'total_value': usd(total_value),
                            'total_total': usd(total_total)})
        

# grand_total = 0
# cash = 0
    # if we don't have a portfolio yet skip the next few lines
    # if display_stocks is not empty execute the following and get cash amount
    #if display_stocks:
    with connection:
        with connection.cursor(cursor_factory = psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute(
                "SELECT cash FROM users WHERE id = %s;", 
                [
                    session["user_id"]
                ]
            )
            cash = float(cursor.fetchall()[0]['cash'])

    grand_total = total_total + cash


    return render_template("index.html",
                            display_stocks=display_stocks,
                            cash=usd(cash),
                            grand_total=usd(grand_total))


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""

    if request.method == "POST":

        # ensure symbol input
        if not request.form.get("symbol"):
            flash('Must provide a symbol', 'danger')
            return render_template("buy.html")

        # get symbol
        symbol = request.form.get("symbol")

        # ensure symbol exists
        if (lookup(symbol) is None):
            flash('This symbol does not exist', 'danger')
            return render_template("buy.html")

        # shares input can't be text
        try:
            float(request.form.get("shares"))
        except ValueError:
            flash('Input must be a number', 'danger')
            return render_template("buy.html")

        # num of share must be positive
        if (float(request.form.get("shares")) < 0):
            flash('Number of shares must be positive', 'danger')
            return render_template("buy.html")

        # num of share must be whole number
        if (float(request.form.get("shares")).is_integer() is False):
            flash('Number of shares must be a whole number', 'danger')
            return render_template("buy.html")


        # get stock info and num of shares
        stock = lookup(symbol)
        shares = int(request.form.get("shares"))

        # get cash of the user
        with connection:
            with connection.cursor(cursor_factory = psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT cash FROM users WHERE id = %s;", 
                    [
                        session["user_id"]
                    ]
                )
                cash = float(cursor.fetchall()[0]['cash'])

        # total_value of transaction
        total_value = (float(stock["price"]) * shares)

        # check if user has enough money for transaction
        if (cash < total_value):
            flash('Insufficient cash funds', 'danger')
            return render_template("buy.html")

        # caculate remaining cash
        money_left = cash - (total_value)

        # update transactions table
        now = datetime.now()
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO transactions (user_id, action, symbol, shares, price, datetime) VALUES (%s, %s, %s, %s, %s, %s);",
                   [
                        session["user_id"], "purchase", symbol, shares, stock["price"], now
                   ]
                )

        # update users table
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE users SET cash = %s WHERE id = %s;", 
                    [
                        money_left, session["user_id"]
                    ]
                )

        symbol = symbol.lower()

        # update balance table
        # check if user already holds any of this stock
        with connection:
            with connection.cursor(cursor_factory = psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT * FROM balance WHERE user_id = %s AND symbol = %s;", 
                    [
                        session["user_id"], symbol
                    ]
                )
                
                count = cursor.rowcount

        # if no previous stock
        if count == 0:
            # insert new row        
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO balance (user_id, symbol, shares, total_value) VALUES (%s, %s, %s, %s);",
                       [
                            session["user_id"], symbol, shares, total_value
                       ]
                    )

       # else if row already exists update its values
        else:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE balance SET shares = shares + %s, total_value = total_value + %s WHERE user_id = %s AND symbol = %s;",
                       [
                            shares, total_value, session["user_id"], symbol
                       ]
                    )

        return redirect("/")

    else:
        return render_template("buy.html")


@app.route("/history")
@login_required
def history():
    """Show history of transactions"""

    with connection:
        with connection.cursor(cursor_factory = psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute(
                "SELECT * FROM transactions WHERE user_id = %s;", 
                [
                    session["user_id"]
                ]
            )
            transactions = cursor.fetchall()

    # formatting
    for transaction in transactions:
        transaction['symbol'] = transaction['symbol'].upper()
        transaction['action'] = transaction['action'].capitalize()
        transaction['price'] = usd(transaction['price'])

    return render_template("history.html", transactions=transactions)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            flash('Must provide username', 'danger')
            return render_template("login.html")

        # Ensure password was submitted
        elif not request.form.get("password"):
            flash('Must provide password', 'danger')
            return render_template("login.html")

        # Query database for username
        with connection:
            with connection.cursor(cursor_factory = psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT * FROM users WHERE username = %s;", 
                    [
                        request.form.get("username")
                    ]
                )
                count = cursor.rowcount
                rows = cursor.fetchall()

        # Ensure username exists and password is correct
        if count != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            flash('Invalid username and/or password', 'danger')
            return render_template("login.html")
        
        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect(url_for('index'))

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""

    if request.method == "POST":

        # check if user entered a symbol
        if not request.form.get("symbol"):
            flash('A symbol is required', 'danger')
            return render_template("quote.html")

        # get symbol
        symbol = request.form.get("symbol")

        # ensure symbol exists
        if (lookup(symbol) is None):
            flash('This symbol does not exist', 'danger')
            return render_template("quote.html")

        # use lookup to return the stock price
        stock = lookup(request.form.get("symbol"))
        stock['symbol'] = symbol.upper()
        stock['price'] = usd(stock['price'])

        return render_template("/quoted.html", stock=stock)

    # get
    else:
        return render_template("quote.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""

    if request.method == "POST":

        # ensure username was submitted
        if not request.form.get("username"):
            flash('Must provide username', 'danger')
            return render_template("register.html")

        # ensure password and confirmation was submitted
        if not request.form.get("password") or not request.form.get("confirmation"):
            flash('Must provide password and confirmation', 'danger')
            return render_template("register.html")

        # query database for username
        with connection:
            with connection.cursor(cursor_factory = psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT * FROM users WHERE username = %s;", 
                    [
                        request.form.get("username")
                    ]
                )
                count = cursor.rowcount
                
        # check if username already exists
        if count != 0:
            flash('Username already exists', 'danger')
            return render_template("register.html")

        # check if password and confirmation match
        if request.form.get("password") != request.form.get("confirmation"):
            flash('Password and confirmation do not match', 'danger')
            return render_template("register.html")

        # store new user in database
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO users (username, hash) VALUES (%s, %s);", 
                    [
                        request.form.get("username"), generate_password_hash(request.form.get("password"))
                    ]
                )

        # redirect to login page
        flash(f'Your Account has been created. You are now able to log in.', 'success')
        return redirect(url_for('login'))

    # if get request
    else:
        return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""

    if request.method == "POST":

        # check for share input
        if not request.form.get('shares'):
            flash('Must provide a number', 'danger')
            return render_template("sell.html")

        # check for symbol input
        if not request.form.get('symbol'):
            flash('Must provide a symbol', 'danger')
            return render_template("sell.html")

        # num of share must be positive
        if float(request.form.get("shares")) < 0:
            flash('Number of shares must be positive', 'danger')
            return render_template("sell.html")
        
        # numb os share must be a whole number
        if (float(request.form.get("shares")).is_integer() is False):
            flash('Number of shares must be a whole number', 'danger')
            return render_template("sell.html")

        # check if user actually owns stock
        with connection:
            with connection.cursor(cursor_factory = psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT * FROM balance WHERE user_id = %s AND symbol = %s AND shares != 0;",
                    [
                        session["user_id"], request.form.get('symbol').lower()
                    ]
                )
                count = cursor.rowcount
                stocks = cursor.fetchall()
                
        if count == 0:
            flash('You do not own any of this stock', 'danger')
            return render_template("sell.html")

        # check if input number does not exceed stocks owned
        if int(stocks[0]['shares']) < int(request.form.get('shares')):
            flash("You do not own that many shares of this stock", 'danger')
            return render_template("sell.html")

        shares = int(request.form.get('shares'))
        price = float((lookup(request.form.get('symbol')))['price'])

        earned = shares * price

        symbol = request.form.get("symbol").lower()

        # update tables

        # update transactions table
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO transactions (user_id, action, symbol, shares, price, datetime) VALUES (%s, %s, %s, %s, %s, %s);",
                   [
                        session["user_id"], "sale", symbol, shares, price, datetime.now()
                   ]
                )

        # update balance table
        # if user sold as many shares as he had; drop row
        if int(stocks[0]['shares']) == shares:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM balance WHERE user_id = %s AND symbol = %s;", 
                        [
                            session["user_id"], symbol
                        ]
                    )

        # else update values
        else:
            with connection: 
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE balance SET shares = shares - %s, total_value = total_value - %s WHERE user_id = %s AND symbol = %s;",
                        [
                            shares, earned, session["user_id"], symbol
                        ]
                    )


        # update users table
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE users SET cash = cash + %s WHERE id = %s;", 
                    [
                        earned, session["user_id"]
                    ]
                )

        # redirect to homepage
        return redirect("/")

    else:

        # get stocks held by user
        with connection:
            with connection.cursor(cursor_factory = psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT * FROM balance WHERE user_id = %s;", 
                    [
                        session["user_id"]
                    ]
                )
                stocks = cursor.fetchall()

        display_stocks = []
        for stock in stocks:
            symbol = (stock['symbol']).upper()
            display_stocks.append({'symbol': symbol})

        return render_template("sell.html", stocks=display_stocks)



@app.route("/deposit", methods=["GET", "POST"])
@login_required
def deposit():
    """ add cash to deposit """

    if request.method == "POST":

        # check for input
        if not request.form.get('cash'):
            flash('Must provide a number', 'danger')
            return render_template("deposit.html")

        # cash must be positive
        if float(request.form.get("cash")) < 0:
            flash('Cash must be positive', 'danger')
            return render_template("deposit.html")

        # get cash
        cash = float(request.form.get("cash"))

        # update users table
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE users SET cash = cash + %s WHERE id = %s;", 
                    [
                        cash, session["user_id"]
                    ]
                )

        return redirect("/")

    else:

        return render_template("deposit.html")


@app.route("/withdraw", methods=["GET", "POST"])
@login_required
def withdraw():
    """ withdraw cash """

    if request.method == "POST":

        # check for input
        if not request.form.get('cash'):
            flash('Must provide a number', 'danger')
            return render_template("withdraw.html")

        # cash must be positive
        if float(request.form.get("cash")) < 0:
            flash('Cash must be positive', 'danger')
            return render_template("withdraw.html")

        # get cash
        withdrawal = float(request.form.get("cash"))

        # withrawal must be less or equal to cash held
        with connection:
            with connection.cursor(cursor_factory = psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT cash FROM users WHERE id = %s;", 
                    [
                        session["user_id"]
                    ]
                )
                cash = cursor.fetchall()

        if withdrawal > float(cash[0]['cash']):
            flash('Withdrawal can not ne bigger than cash deposits', 'danger')
            return render_template("withdraw.html")

        # update users table
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE users SET cash = cash - %s WHERE id = %s;", 
                    [
                        withdrawal, session["user_id"]
                    ]
                )

        return redirect("/")

    else:

        return render_template("withdraw.html")
    

@app.route("/optimise", methods=["GET", "POST"])
@login_required
def optimise():

    if request.method == "POST":
        
        # getting the stock held by user 
        with connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT * FROM balance WHERE user_id = %s;",
                    [
                        session["user_id"]
                    ]
                )
                stocks = cursor.fetchall()

        tickers_list = []
        list_of_tickers = []
        total_total = 0
        for stock in stocks:
            ticker = stock['symbol'].upper()
            shares = stock['shares']
            total_value = stock['total_value'] # shares * (current) price 
            total_total += total_value # total_value of all portfolio 
            tickers_list.append({'ticker': ticker,
                                 'shares': shares,
                                 'total_value': usd(total_value)})
            list_of_tickers.append(ticker)

        # now all the stock names that the users holds should be in the tickers list
        # get the adj close price since 2018
        year = str(request.form.get("year"))+'-1-1'
        data = yf.download(list_of_tickers, year)['Adj Close']
        # this should be a dataframe with the date as the index, tickers as columns and adj close as the values

        # mean
        mu = expected_returns.mean_historical_return(data) 
        # covariance of every stock 
        S = risk_models.sample_cov(data)

        # Optimising for maximal Sharpe ratio
        ef = EfficientFrontier(mu, S) # expected returns and covariance matrix as input
        weights = ef.max_sharpe() # Optimising weights for Sharpe ratio maximization

        clean_weights = ef.clean_weights() # rounds the weights and clips near-zeros => returns a dict _OrderedDict_([('ticker', 0.632), ('ticker2', 0.234)])
        # convert the OrderedDict to a pandas Series
        series = pd.Series(clean_weights)

        # turn weights into a number of shares
        # get total value of current portfolio
        pf_value = 0
        for stock in stocks:
            pf_value += stock['total_value']

        latest_prices = get_latest_prices(data)
        da = DiscreteAllocation(clean_weights, latest_prices, total_portfolio_value=pf_value)
        allocation, leftover = da.greedy_portfolio()

        display_stocks = []
        for ticker in list_of_tickers:
            symbol = ticker
            weight = series[ticker]
            if ticker in allocation:
                num = allocation[ticker]
            else:
                num = 0
            display_stocks.append({'symbol': symbol,
                                'weight': weight,
                                'shares': num,
                                })

        # Visualization (Historical Performance of Portfolio ignoring purchase day etc.)

        # calculate old weights
        old_weights = []
        for ticker in tickers_list:
            symbol = ticker['ticker']
            total_value = ticker['total_value'][1:]
            weight = float(total_value.replace(',','')) / total_total
            old_weights.append({'symbol': symbol,
                                'weight': weight})
            
        # apply weights to returns
        dates = data.index # extract the index (dates) from data to use as index for new dataframe
        old_portfolio_return = pd.DataFrame({'date': dates})
        old_portfolio_return.set_index('date')

        for symbol in old_weights:

            close = data.loc[:, symbol['symbol']] 
            close = close.reset_index(drop=True)

            returns = pd.Series()
            for i in range(len(close)):
                if i == 0:
                    returns[i] = 0
                else: 
                    returns[i] = (close[i] - close[i-1]) / close[i-1] 

            weighted_return = symbol['weight'] * returns

            old_portfolio_return[symbol['symbol']] = weighted_return # add the weighted return as a column to the dataframe

        # sum up to single column
        
        old_portfolio_return['total_return'] = old_portfolio_return[list_of_tickers].sum(axis=1)
        # calculate cumulative product
        old_portfolio_return['cum_prod'] = 1 * (1 + old_portfolio_return["total_return"]).cumprod()

        # OPTIMISED PORTFOLIO

        new_portfolio_return = pd.DataFrame({'date': dates})
        new_portfolio_return.set_index('date')

        for key, value in clean_weights.items():

            close = data.loc[:, key]
            close = close.reset_index(drop=True)

            returns = pd.Series()
            for i in range(len(close)):
                if i == 0:
                    returns[i] = 0
                else:
                    returns[i] = (close[i] - close[i-1]) / close[i-1]
            weighted_return = value * returns

            new_portfolio_return[key] = weighted_return 

        # sum up to single column
            
        new_portfolio_return['total_return'] = new_portfolio_return[list_of_tickers].sum(axis=1)
        # calculate cumulative product
        new_portfolio_return['cum_prod'] = 1 * (1 + new_portfolio_return["total_return"]).cumprod()


        
        fig = create_figure(old_portfolio_return, new_portfolio_return)
        pngImage = BytesIO()
        FigureCanvas(fig).print_png(pngImage)
        
        # Encode PNG image to base64 string
        pngImageB64String = "data:image/png;base64,"
        pngImageB64String += base64.b64encode(pngImage.getvalue()).decode('utf8')

        return render_template("optimised.html",
                                display_stocks=display_stocks,
                                leftover=usd(leftover),
                                pf_value=usd(pf_value),
                                image=pngImageB64String
                                )
    else:

        year = datetime.today().year
        years = range(year, 1999, -1)

        return render_template("optimise.html", years=years)

def create_figure(data, data2):
    fig, ax = plt.subplots()
    plt.plot(data.date, data.cum_prod, label = 'Old Portfolio') #### 
    plt.plot(data2.date, data2.cum_prod, label = 'Optimised Portfolio') #### 
    plt.xlabel('Date')
    plt.ylabel('Cumulative Returns')
    plt.title('Comparison')
    plt.legend()
    return fig


@app.route("/optimised", methods=["GET", "POST"])
@login_required
def optimised():
    
    if request.method == "POST":

        return render_template("/")
    else:
        
        return render_template("/optimised")


if __name__ == '__main__':
    app.run(debug=True)


