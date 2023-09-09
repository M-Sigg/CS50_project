# Portfolio Optimisation 
#### Video Demo: <https://youtu.be/7DOmEyaPyjw>
## Description:
 Building upon the CS50 Finance Flask application that we built during the course I added the feature for the user to optimise their portfolio using a Markowitz's Mean-Variance Optimisation.

 ### Mean-Variance Optimisation
 Markowitz Mean-Variance Optimisation is based on the idea that investors are risk-avers and favor an investment that has a better risk-return relationship. My application allows the user to artificially 'buy' and 'sell' stocks retrieving the data from yahoo finance through the yfinance library. Based on the acquired stocks the programm calculates the risk of these assets based on their volatilty. Given this risk-level and a user-given time horizon the programm optimises the expected return and assigns each stock new weights and tells the user to how many shares of each stock this corresponds to. Additionally, given the weights of the old and new, optimised portfolio the programm calculates the weighted returns of each stocks, adding them together to get the overall daily portfolio returns and then calculates the cumulative returns based on that, which then get visualized in a graph that allows the user to compare the historical performance of their portfolio vs. the optimised portfolio.

 ### Deviations from the CS50 app
 I also adapted the inital CS50 app quite heavily. I implemented my own helper functions and retrieved the data through the yfinance library. Additionally I set up a PostgreSQL database through <railway.app> and connected to it using the psycopg2 library, instead of using sqlite3 and the CS50 library. Also the apology function from the course was replaced by the flash function of the Flask library. 